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
from datetime import UTC, datetime
from typing import Any

import structlog
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import ImmichAlbumSyncEventData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService

logger = structlog.get_logger()

EVENT_TYPE_IMMICH_ALBUM_CREATED = "immich_album.created"
EVENT_TYPE_IMMICH_ALBUM_UPDATED = "immich_album.updated"

INTEGRATION_SOURCE = "immich_album"
EXTERNAL_SYSTEM = "immich"
EXTERNAL_ENTITY_TYPE = "album"
INTERNAL_ENTITY_TYPE = "journal"

# Fields protected once a journal is edited locally after its last sync.
_PROTECTED_FIELDS = (
    "title",
    "content",
    "event_date_range_start",
    "event_date_range_end",
)


class ImmichAlbumOutboxEventProcessingError(Exception):
    """Raised when Immich album outbox event processing fails."""


class ImmichAlbumOutboxEventProcessor:
    """Creates/updates PHOTO_ALBUM journals from Immich album sync events."""

    def __init__(
        self,
        journal_service: JournalService,
        connection: AsyncConnection,
    ) -> None:
        """Initialize with a journal service and database connection."""
        self.journal_service = journal_service
        self.connection = connection
        self.journal_repo = SqlJournalRepository(connection)
        self.sync_metadata_repo = SyncMetadataRepository(connection)

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

        Checks the album external_reference, then the sync_metadata link, then
        the event's ``existing_journal_id`` — returning the first that points at
        a journal that still exists. This makes create/update idempotent even if
        one of the link rows is missing or corrupted.
        """
        ref = await self._find_external_reference(payload.external_id)
        if ref is not None and await self._journal_exists(ref.internal_entity_id):
            return int(ref.internal_entity_id)

        metadata = await self.sync_metadata_repo.find_by_external_id(
            INTEGRATION_SOURCE, payload.external_id
        )
        if (
            metadata is not None
            and metadata.internal_id is not None
            and await self._journal_exists(metadata.internal_id)
        ):
            return int(metadata.internal_id)

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
        await self._upsert_external_reference(created.id, payload, bump_anchor=True)

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
        ref = await self._find_external_reference(
            payload.external_id, journal_id=journal_id
        )
        # Without a link anchor we cannot tell whether the journal was edited
        # locally, so treat it as protected to avoid overwriting user data (the
        # anchor is re-established below and normal sync resumes next cycle).
        if ref is None:
            has_local_edits = True
        else:
            has_local_edits = self._has_local_edits(existing.updated_at, ref.updated_at)

        if not has_local_edits:
            merged = self._build_journal(payload.journal_data, journal_id=journal_id)
            merged.user_id = existing.user_id
            merged.parent_id = existing.parent_id
            merged.order = existing.order
            await self.journal_service.update_journal(
                merged,
                changed_fields=dict.fromkeys(_PROTECTED_FIELDS, True),
                transaction=self.connection,
            )

        # Always refresh album display metadata (name / asset count / url) so it
        # cannot go stale. Only advance the merge anchor (updated_at) when we
        # actually applied inbound changes, so a locally edited journal stays
        # protected on future syncs.
        await self._upsert_external_reference(
            journal_id, payload, bump_anchor=not has_local_edits
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
    def _reference_data(payload: ImmichAlbumSyncEventData) -> str:
        """Build the album external reference's reference_data JSON."""
        metadata = payload.album_metadata or {}
        data = {
            "album_id": payload.external_id,
            "album_name": metadata.get("album_name"),
            "asset_count": metadata.get("asset_count"),
            "album_url": metadata.get("album_url"),
            "thumbnail_asset_id": metadata.get("thumbnail_asset_id"),
        }
        return json.dumps({k: v for k, v in data.items() if v is not None})

    async def _find_external_reference(
        self, album_id: str, journal_id: int | None = None
    ) -> Any | None:
        """Find the album external reference row by Immich album ID.

        When ``journal_id`` is given, the lookup is constrained to the reference
        pointing at that journal, so merge protection compares against the right
        anchor even if multiple references exist for the same album.
        """
        params: dict[str, Any] = {
            "external_system": EXTERNAL_SYSTEM,
            "external_entity_type": EXTERNAL_ENTITY_TYPE,
            "external_entity_id": album_id,
            "internal_entity_type": INTERNAL_ENTITY_TYPE,
        }
        journal_filter = ""
        if journal_id is not None:
            journal_filter = "AND internal_entity_id = :internal_entity_id"
            params["internal_entity_id"] = journal_id

        result = await self.connection.execute(
            text(f"""
                SELECT id, internal_entity_id, updated_at
                FROM external_references
                WHERE external_system = :external_system
                  AND external_entity_type = :external_entity_type
                  AND external_entity_id = :external_entity_id
                  AND internal_entity_type = :internal_entity_type
                  {journal_filter}
                ORDER BY id DESC
                LIMIT 1
            """),
            params,
        )
        return result.fetchone()

    async def _upsert_external_reference(
        self,
        journal_id: int,
        payload: ImmichAlbumSyncEventData,
        *,
        bump_anchor: bool,
    ) -> None:
        """Insert or update the journal-to-album external reference.

        Refreshes ``reference_data`` (album display metadata) and repoints the
        link to ``journal_id``. ``updated_at`` — the merge-protection anchor —
        is only advanced when ``bump_anchor`` is True (i.e. inbound changes were
        applied); when False the existing anchor is preserved so a locally
        edited journal stays protected.

        ``external_references.updated_at`` uses an app-level (not DB) ``onupdate``
        default, so a raw UPDATE that omits the column leaves it untouched.
        """
        now = datetime.now(UTC)
        params: dict[str, Any] = {
            "journal_id": journal_id,
            "reference_data": self._reference_data(payload),
            "external_system": EXTERNAL_SYSTEM,
            "external_entity_type": EXTERNAL_ENTITY_TYPE,
            "external_entity_id": payload.external_id,
            "internal_entity_type": INTERNAL_ENTITY_TYPE,
            "now": now,
        }

        anchor_assignment = ", updated_at = :now" if bump_anchor else ""
        result = await self.connection.execute(
            text(f"""
                UPDATE external_references
                SET internal_entity_id = :journal_id,
                    reference_data = :reference_data{anchor_assignment}
                WHERE external_system = :external_system
                  AND external_entity_type = :external_entity_type
                  AND external_entity_id = :external_entity_id
                  AND internal_entity_type = :internal_entity_type
            """),
            params,
        )

        if result.rowcount == 0:
            await self.connection.execute(
                text("""
                    INSERT INTO external_references
                        (internal_entity_type, internal_entity_id, external_system,
                         external_entity_type, external_entity_id, reference_data,
                         created_at, updated_at)
                    VALUES
                        (:internal_entity_type, :journal_id, :external_system,
                         :external_entity_type, :external_entity_id, :reference_data,
                         :now, :now)
                """),
                params,
            )
