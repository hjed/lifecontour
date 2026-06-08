"""Immich Album Outbox Event Processor.

Processes ``immich_album.created`` and ``immich_album.updated`` outbox events
from the Immich worker to create/update ``PHOTO_ALBUM`` journals.

Unlike calendar-sourced journals (handled by ``JournalOutboxEventProcessor``),
Immich albums are tracked with ``sync_metadata`` (integration_source =
``immich_album``) and an ``external_references`` record linking the journal to
the Immich album — there is no calendar or external event link.

Field merge protection mirrors Google Calendar's ``InboundFieldMerger``: when a
journal has been edited locally since it was last synced
(``journal.updated_at > external_reference.updated_at``), the local title,
content and date range are preserved and the inbound album values are ignored.
"""

import json
from datetime import datetime
from typing import Any

import structlog
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import ImmichAlbumSyncEventData
from core_shared.repositories.external_reference_repository import (
    ExternalReferenceRepository,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService

logger = structlog.get_logger()

EVENT_TYPE_IMMICH_ALBUM_CREATED = "immich_album.created"
EVENT_TYPE_IMMICH_ALBUM_UPDATED = "immich_album.updated"

INTEGRATION_SOURCE = "immich_album"

# changed_fields keys for the emitted JournalUpdated event. These are the fields
# protected from inbound overwrite once a journal is edited locally, named to
# match the repo-wide convention (a single ``event_date_range`` key rather than
# separate ``_start`` / ``_end`` keys) so consumers don't special-case albums.
_CHANGED_FIELDS = (
    "title",
    "content",
    "event_date_range",
)


class ImmichAlbumOutboxEventProcessingError(Exception):
    """Raised when Immich album outbox event processing fails."""


class ImmichAlbumOutboxEventProcessor:
    """Creates/updates PHOTO_ALBUM journals from Immich album sync events."""

    def __init__(
        self,
        journal_service: JournalService,
        connection: AsyncConnection,
        relationship_repo: SqlJournalContactRelationshipRepository | None = None,
        ext_ref_repo: ExternalReferenceRepository | None = None,
    ) -> None:
        """Initialize with a journal service and database connection.

        ``relationship_repo`` and ``ext_ref_repo`` are used for participant
        detection (resolving tagged Immich people to local contacts and keeping
        the journal's PARTICIPANT relationships in sync). They default to
        connection-backed implementations so existing callers need not change.
        """
        self.journal_service = journal_service
        self.connection = connection
        self.journal_repo = SqlJournalRepository(connection)
        self.sync_metadata_repo = SyncMetadataRepository(connection)
        self.album_link_repo = AlbumSyncReadRepository(connection)
        self.relationship_repo = (
            relationship_repo or SqlJournalContactRelationshipRepository(connection)
        )
        self.ext_ref_repo = ext_ref_repo or ExternalReferenceRepository(connection)

    async def process_event(self, event: OutboxEvent) -> dict[str, Any]:
        """Process a single Immich album outbox event."""
        logger.info(
            "Processing Immich album outbox event",
            event_id=event.id,
            event_type=event.event_type,
        )

        payload = ImmichAlbumSyncEventData.model_validate(event.event_data)

        if event.event_type == EVENT_TYPE_IMMICH_ALBUM_CREATED:
            return await self._process_created(payload)
        if event.event_type == EVENT_TYPE_IMMICH_ALBUM_UPDATED:
            return await self._process_updated(payload)

        raise ImmichAlbumOutboxEventProcessingError(
            f"Unknown Immich album event type: {event.event_type}"
        )

    # -- Create / Update dispatch ----------------------------------------

    async def _process_created(
        self, payload: ImmichAlbumSyncEventData
    ) -> dict[str, Any]:
        """Handle an ``immich_album.created`` event.

        Resolves any existing journal already linked to this album (via
        external_reference *or* sync_metadata) so a retried create cannot
        duplicate the journal; otherwise creates a new one.
        """
        journal_id = await self._existing_journal_id(payload)
        if journal_id is not None:
            return await self._apply_update(payload, journal_id)
        return await self._apply_create(payload)

    async def _process_updated(
        self, payload: ImmichAlbumSyncEventData
    ) -> dict[str, Any]:
        """Handle an ``immich_album.updated`` event.

        Updates the linked journal, or creates one if the album has not been
        imported yet.
        """
        journal_id = await self._existing_journal_id(payload)
        if journal_id is None:
            return await self._apply_create(payload)
        return await self._apply_update(payload, journal_id)

    async def _existing_journal_id(
        self, payload: ImmichAlbumSyncEventData
    ) -> int | None:
        """Resolve the existing, still-present journal id for this album.

        ``sync_metadata`` is the authoritative link (unique per album), so it is
        checked first, then the album external_reference, then the event's
        ``existing_journal_id`` — returning the first that points at a journal
        that still exists. Preferring sync_metadata prevents a stray/duplicate
        external_reference from repointing the album at the wrong journal.
        """
        metadata = await self.sync_metadata_repo.find_by_external_id(
            INTEGRATION_SOURCE, payload.external_id
        )
        if (
            metadata is not None
            and metadata.internal_id is not None
            and await self._journal_exists(metadata.internal_id)
        ):
            return int(metadata.internal_id)

        link = await self.album_link_repo.find_link(payload.external_id)
        if link is not None and await self._journal_exists(link.internal_entity_id):
            return int(link.internal_entity_id)

        if payload.existing_journal_id is not None and await self._journal_exists(
            payload.existing_journal_id
        ):
            return payload.existing_journal_id

        return None

    async def _journal_exists(self, journal_id: int) -> bool:
        """Return True if a journal with this id still exists."""
        return await self.journal_repo.find_by_id(journal_id) is not None

    async def _apply_create(self, payload: ImmichAlbumSyncEventData) -> dict[str, Any]:
        """Create a new PHOTO_ALBUM journal and its sync links."""
        journal = self._build_journal(payload.journal_data)
        created = await self.journal_service.create_journal(journal, self.connection)
        if created.id is None:
            raise ImmichAlbumOutboxEventProcessingError("Created journal has no ID")

        await self.sync_metadata_repo.upsert(
            integration_source=INTEGRATION_SOURCE,
            external_id=payload.external_id,
            version_hash=payload.version_hash,
            internal_id=created.id,
        )

        # Participants are not merge-protected, so a new album always reconciles
        # its tagged people. There is no prior immich set on create.
        reference_data = self._reference_data(payload)
        reference_data["participant_contact_ids"] = await self._sync_participants(
            created.id, payload, {}, has_local_edits=False
        )

        await self.album_link_repo.upsert_link(
            created.id,
            payload.external_id,
            reference_data,
            bump_anchor=True,
        )

        logger.info(
            "Created PHOTO_ALBUM journal from Immich album",
            journal_id=created.id,
            album_id=payload.external_id,
        )
        return {
            "status": "created",
            "event_type": EVENT_TYPE_IMMICH_ALBUM_CREATED,
            "journal_id": created.id,
            "album_id": payload.external_id,
        }

    async def _apply_update(
        self, payload: ImmichAlbumSyncEventData, journal_id: int
    ) -> dict[str, Any]:
        """Update a linked album journal, honouring local-edit merge protection."""
        existing = await self.journal_repo.find_by_id(journal_id)
        if existing is None:
            # Journal vanished between checks — recreate it.
            return await self._apply_create(payload)

        metadata = await self.sync_metadata_repo.find_by_external_id(
            INTEGRATION_SOURCE, payload.external_id
        )
        if not self.sync_metadata_repo.should_sync(metadata, payload.version_hash):
            logger.info("Skipping unchanged Immich album", album_id=payload.external_id)
            return {
                "status": "skipped",
                "reason": "unchanged",
                "journal_id": journal_id,
                "album_id": payload.external_id,
            }

        # Look up the anchor for *this* journal specifically: if several album
        # references somehow exist, we must compare against the one pointing at
        # the journal we are updating, not just the newest.
        link = await self.album_link_repo.find_link(
            payload.external_id, journal_id=journal_id
        )
        # Without a link anchor we cannot tell whether the journal was edited
        # locally, so treat it as protected to avoid overwriting user data (the
        # anchor is re-established below and normal sync resumes next cycle).
        if link is None:
            has_local_edits = True
            prev_reference_data: dict[str, Any] = {}
        else:
            has_local_edits = self._has_local_edits(
                existing.updated_at, link.updated_at
            )
            prev_reference_data = self._decode_reference_data(link.reference_data)

        if not has_local_edits:
            merged = self._build_journal(payload.journal_data, journal_id=journal_id)
            merged.user_id = existing.user_id
            merged.parent_id = existing.parent_id
            merged.order = existing.order
            await self.journal_service.update_journal(
                merged,
                changed_fields=dict.fromkeys(_CHANGED_FIELDS, True),
                transaction=self.connection,
            )

        # Participants are reconciled regardless of merge protection: newly
        # tagged people are always added, but removals are skipped when the
        # journal was edited locally (add-only), preserving a user-curated list.
        reference_data = self._reference_data(payload)
        reference_data["participant_contact_ids"] = await self._sync_participants(
            journal_id, payload, prev_reference_data, has_local_edits=has_local_edits
        )

        # Always refresh album display metadata (name / asset count / url) so it
        # cannot go stale. Only advance the merge anchor (updated_at) when we
        # actually applied inbound changes, so a locally edited journal stays
        # protected on future syncs.
        await self.album_link_repo.upsert_link(
            journal_id,
            payload.external_id,
            reference_data,
            bump_anchor=not has_local_edits,
        )

        await self.sync_metadata_repo.upsert(
            integration_source=INTEGRATION_SOURCE,
            external_id=payload.external_id,
            version_hash=payload.version_hash,
            internal_id=journal_id,
        )

        logger.info(
            "Updated PHOTO_ALBUM journal from Immich album",
            journal_id=journal_id,
            album_id=payload.external_id,
            protected=has_local_edits,
        )
        return {
            "status": "protected" if has_local_edits else "updated",
            "event_type": EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            "journal_id": journal_id,
            "album_id": payload.external_id,
        }

    # -- Helpers ----------------------------------------------------------

    @staticmethod
    def _has_local_edits(
        journal_updated_at: datetime | None,
        link_updated_at: datetime | None,
    ) -> bool:
        """Return True if the journal was edited after its last album sync."""
        if journal_updated_at is None or link_updated_at is None:
            return False
        return journal_updated_at > link_updated_at

    @staticmethod
    def _build_journal(
        journal_data: dict[str, Any], journal_id: int | None = None
    ) -> Journal:
        """Build a Journal entity from album journal_data."""
        start = datetime.fromisoformat(journal_data["event_date_range_start"])
        end = datetime.fromisoformat(journal_data["event_date_range_end"])
        return Journal(
            id=journal_id,
            user_id=journal_data["user_id"],
            title=journal_data["title"],
            content=journal_data.get("content", ""),
            event_date_range=EventDateRange(start=start, end=end),
        )

    @staticmethod
    def _reference_data(payload: ImmichAlbumSyncEventData) -> dict[str, Any]:
        """Build the album external reference's display metadata dict."""
        metadata = payload.album_metadata or {}
        data = {
            "album_id": payload.external_id,
            "album_name": metadata.get("album_name"),
            "asset_count": metadata.get("asset_count"),
            "album_url": metadata.get("album_url"),
            "thumbnail_asset_id": metadata.get("thumbnail_asset_id"),
            "shared_link_url": metadata.get("shared_link_url"),
        }
        return {k: v for k, v in data.items() if v is not None}

    @staticmethod
    def _decode_reference_data(reference_data: str | None) -> dict[str, Any]:
        """Decode an album reference_data JSON string, tolerating bad rows."""
        if not reference_data:
            return {}
        try:
            decoded = json.loads(reference_data)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    async def _sync_participants(
        self,
        journal_id: int,
        payload: ImmichAlbumSyncEventData,
        prev_reference_data: dict[str, Any],
        *,
        has_local_edits: bool,
    ) -> list[int]:
        """Reconcile journal PARTICIPANT relationships from album people tags.

        Tagged Immich people are resolved to local contacts via
        ``ExternalReference`` (unresolved people are skipped — no orphans).
        Newly tagged contacts are always added. Removals (contacts that left the
        immich-managed set) are applied only when the journal has not been edited
        locally — otherwise the sync is add-only so a user-curated participant
        list is preserved. Only contacts in the immich-managed set
        (``participant_contact_ids`` from the prior reference_data) are ever
        removed, so manually-added participants are never touched.

        Returns the new immich-managed contact id set to persist in reference_data.
        """
        people = payload.album_metadata.get("people") or []
        person_ids = [p["id"] for p in people if isinstance(p, dict) and p.get("id")]
        resolved = await self.ext_ref_repo.get_contact_ids_by_immich_person_ids(
            person_ids
        )
        desired = set(resolved.values())

        existing_rows = await self.relationship_repo.get_by_journal_and_type(
            journal_id, JournalContactRelationshipType.PARTICIPANT
        )
        existing_contact_ids = {row.contact_id for row in existing_rows}

        # Additions always run (participants are not merge-protected).
        for contact_id in sorted(desired - existing_contact_ids):
            await self.relationship_repo.create(
                JournalContactRelationship(
                    journal_id=journal_id,
                    contact_id=contact_id,
                    relationship_type=JournalContactRelationshipType.PARTICIPANT,
                    status=AttendeeStatus.ATTENDED,
                )
            )

        prev = {
            int(cid) for cid in prev_reference_data.get("participant_contact_ids", [])
        }

        if has_local_edits:
            # Add-only: keep the un-removed immich participants and the new ones.
            return sorted(prev | desired)

        # Remove only contacts that were immich-managed and are now untagged.
        for contact_id in sorted(prev - desired):
            await self.relationship_repo.delete(
                journal_id,
                contact_id,
                JournalContactRelationshipType.PARTICIPANT,
            )
        return sorted(desired)
