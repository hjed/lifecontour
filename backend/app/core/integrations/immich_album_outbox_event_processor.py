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

    # -- Create -----------------------------------------------------------

    async def _process_created(
        self, payload: ImmichAlbumSyncEventData
    ) -> dict[str, Any]:
        """Create a PHOTO_ALBUM journal, or update if the album already links."""
        existing_ref = await self._find_external_reference(payload.external_id)
        if existing_ref is not None:
            # Already linked (e.g. a retried create) — treat as an update.
            return await self._process_updated(payload)

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
        await self._create_external_reference(created.id, payload)

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

    # -- Update -----------------------------------------------------------

    async def _process_updated(
        self, payload: ImmichAlbumSyncEventData
    ) -> dict[str, Any]:
        """Update an album journal, honouring local-edit merge protection."""
        ref = await self._find_external_reference(payload.external_id)
        journal_id = ref.internal_entity_id if ref else payload.existing_journal_id

        if journal_id is None:
            # No link yet — fall back to creating the journal.
            return await self._process_created(payload)

        existing = await self.journal_repo.find_by_id(journal_id)
        if existing is None:
            # Link points at a deleted journal — recreate it.
            return await self._process_created(payload)

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

        link_updated_at = ref.updated_at if ref else None
        has_local_edits = self._has_local_edits(existing.updated_at, link_updated_at)

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
            await self._touch_external_reference(payload, journal_id)

        # Always record that we have processed this album version so we do not
        # reprocess it; protected journals keep their (older) link timestamp so
        # local edits remain protected on future syncs.
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

    async def _find_external_reference(self, album_id: str) -> Any | None:
        """Find the album external reference row by Immich album ID."""
        result = await self.connection.execute(
            text("""
                SELECT id, internal_entity_id, updated_at
                FROM external_references
                WHERE external_system = :external_system
                  AND external_entity_type = :external_entity_type
                  AND external_entity_id = :external_entity_id
                  AND internal_entity_type = :internal_entity_type
                ORDER BY id DESC
                LIMIT 1
            """),
            {
                "external_system": EXTERNAL_SYSTEM,
                "external_entity_type": EXTERNAL_ENTITY_TYPE,
                "external_entity_id": album_id,
                "internal_entity_type": INTERNAL_ENTITY_TYPE,
            },
        )
        return result.fetchone()

    async def _create_external_reference(
        self, journal_id: int, payload: ImmichAlbumSyncEventData
    ) -> None:
        """Insert the journal-to-album external reference."""
        now = datetime.now(UTC)
        await self.connection.execute(
            text("""
                INSERT INTO external_references
                    (internal_entity_type, internal_entity_id, external_system,
                     external_entity_type, external_entity_id, reference_data,
                     created_at, updated_at)
                VALUES
                    (:internal_entity_type, :internal_entity_id, :external_system,
                     :external_entity_type, :external_entity_id, :reference_data,
                     :created_at, :updated_at)
            """),
            {
                "internal_entity_type": INTERNAL_ENTITY_TYPE,
                "internal_entity_id": journal_id,
                "external_system": EXTERNAL_SYSTEM,
                "external_entity_type": EXTERNAL_ENTITY_TYPE,
                "external_entity_id": payload.external_id,
                "reference_data": self._reference_data(payload),
                "created_at": now,
                "updated_at": now,
            },
        )

    async def _touch_external_reference(
        self, payload: ImmichAlbumSyncEventData, journal_id: int
    ) -> None:
        """Refresh reference_data and updated_at after applying an album update.

        Bumping ``updated_at`` marks "last synced now" so the next sync only
        treats the journal as locally edited if it changes again afterwards.
        """
        now = datetime.now(UTC)
        await self.connection.execute(
            text("""
                UPDATE external_references
                SET reference_data = :reference_data,
                    updated_at = :updated_at
                WHERE external_system = :external_system
                  AND external_entity_type = :external_entity_type
                  AND external_entity_id = :external_entity_id
                  AND internal_entity_type = :internal_entity_type
                  AND internal_entity_id = :internal_entity_id
            """),
            {
                "reference_data": self._reference_data(payload),
                "updated_at": now,
                "external_system": EXTERNAL_SYSTEM,
                "external_entity_type": EXTERNAL_ENTITY_TYPE,
                "external_entity_id": payload.external_id,
                "internal_entity_type": INTERNAL_ENTITY_TYPE,
                "internal_entity_id": journal_id,
            },
        )
