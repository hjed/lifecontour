"""
Journal Outbox Event Processor for handling inbound journal sync events.

Processes journal_event.created, journal_event.updated, and
journal_event.conflicted outbox events from integration workers to
create/update journals in the core system.
"""

from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

import structlog
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.journal_service import JournalService

logger = structlog.get_logger()

# Event type constants
EVENT_TYPE_JOURNAL_EVENT_CREATED = "journal_event.created"
EVENT_TYPE_JOURNAL_EVENT_UPDATED = "journal_event.updated"
EVENT_TYPE_JOURNAL_EVENT_CONFLICTED = "journal_event.conflicted"


class JournalOutboxEventProcessingError(Exception):
    """Raised when journal outbox event processing fails."""


class JournalOutboxEventProcessor:
    """
    Processes inbound journal sync events from integration workers.

    Handles journal_event.* outbox events by creating/updating journals,
    saving calendar info, and managing external event links.
    """

    def __init__(
        self,
        journal_service: JournalService,
        connection: AsyncConnection,
    ) -> None:
        """
        Initialize the journal outbox event processor.

        Args:
            journal_service: Service for journal operations
            connection: Database connection for transactions
        """
        self.journal_service = journal_service
        self.connection = connection

    async def process_event(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a single journal outbox event.

        Args:
            event: Outbox event to process

        Returns:
            Processing result dictionary

        Raises:
            JournalOutboxEventProcessingError: If event processing fails
        """
        logger.info(
            "Processing journal outbox event",
            event_id=event.id,
            event_type=event.event_type,
        )

        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_CREATED:
            return await self._process_journal_created(event)
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_UPDATED:
            return await self._process_journal_updated(event)
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_CONFLICTED:
            return await self._process_journal_conflicted(event)

        raise JournalOutboxEventProcessingError(
            f"Unknown journal event type: {event.event_type}"
        )

    async def _process_journal_created(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.created event.

        Creates a new journal, saves calendar info, and creates an
        external event link.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        journal_data = event_data["journal_data"]
        calendar_info_data = event_data["calendar_info_data"]
        external_event_id = event_data["external_event_id"]
        calendar_id = event_data["calendar_id"]
        etag = event_data.get("etag")

        # Build the journal entity
        journal = self._build_journal_from_data(journal_data)

        # Create the journal via service
        created_journal = await self.journal_service.create_journal(
            journal, self.connection
        )

        if created_journal.id is None:
            raise JournalOutboxEventProcessingError("Created journal has no ID")

        # Save calendar info
        await self._save_calendar_info(created_journal.id, calendar_info_data)

        # Create external event link
        await self._create_external_event_link(
            journal_id=created_journal.id,
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
            etag=etag,
        )

        logger.info(
            "Created journal from inbound sync event",
            journal_id=created_journal.id,
            external_event_id=external_event_id,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_CREATED,
            "journal_id": created_journal.id,
            "external_event_id": external_event_id,
        }

    async def _process_journal_updated(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.updated event.

        Looks up the existing journal, checks for ETag-based idempotency,
        updates the journal fields, and updates the external event link.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        journal_data = event_data["journal_data"]
        calendar_info_data = event_data["calendar_info_data"]
        external_event_id = event_data["external_event_id"]
        calendar_id = event_data["calendar_id"]
        etag = event_data.get("etag")
        existing_journal_id = event_data.get("existing_journal_id")

        if existing_journal_id is None:
            raise JournalOutboxEventProcessingError(
                "journal_event.updated requires existing_journal_id"
            )

        # Fetch existing journal
        existing_journal = await self._find_journal_by_id(existing_journal_id)
        if existing_journal is None:
            raise JournalOutboxEventProcessingError(
                f"Journal {existing_journal_id} not found for update"
            )

        # ETag idempotency check
        existing_link = await self._find_external_event_link(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
        )
        if existing_link and existing_link.external_version == etag:
            logger.info(
                "Journal update skipped - ETag unchanged",
                journal_id=existing_journal_id,
                etag=etag,
            )
            return {
                "status": "skipped",
                "reason": "etag_unchanged",
                "event_type": EVENT_TYPE_JOURNAL_EVENT_UPDATED,
                "journal_id": existing_journal_id,
            }

        # Build updated journal
        updated_journal = self._build_journal_from_data(
            journal_data, journal_id=existing_journal_id
        )

        # Calculate changed fields
        changed_fields: dict[str, Any] = {}
        if updated_journal.title != existing_journal.title:
            changed_fields["title"] = (existing_journal.title, updated_journal.title)
        if updated_journal.content != existing_journal.content:
            changed_fields["content"] = (
                existing_journal.content,
                updated_journal.content,
            )

        # Update via journal service
        saved_journal = await self.journal_service.update_journal(
            updated_journal, changed_fields, self.connection
        )

        # Update calendar info
        if saved_journal.id is not None:
            await self._save_calendar_info(saved_journal.id, calendar_info_data)

        # Update external event link ETag
        await self._update_external_event_link_etag(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
            etag=etag,
        )

        logger.info(
            "Updated journal from inbound sync event",
            journal_id=saved_journal.id,
            external_event_id=external_event_id,
            changed_fields=list(changed_fields.keys()),
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_UPDATED,
            "journal_id": saved_journal.id,
            "external_event_id": external_event_id,
        }

    async def _process_journal_conflicted(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.conflicted event.

        Marks the external event link as conflicted so users can resolve.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        external_event_id = event_data["external_event_id"]
        calendar_id = event_data["calendar_id"]

        # Mark link as conflicted
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET sync_status = 'conflicted',
                    updated_at = :now
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "calendar_id": UUID(calendar_id),
                "external_event_id": external_event_id,
                "now": datetime.now(UTC),
            },
        )

        logger.info(
            "Marked journal event link as conflicted",
            external_event_id=external_event_id,
            calendar_id=calendar_id,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_CONFLICTED,
            "external_event_id": external_event_id,
        }

    # ── Helper methods ──────────────────────────────────────────────────

    @staticmethod
    def _build_journal_from_data(
        journal_data: dict[str, Any],
        journal_id: int | None = None,
    ) -> Journal:
        """Build a Journal entity from outbox event payload data."""
        start_str = journal_data.get("event_date_range_start")
        end_str = journal_data.get("event_date_range_end")

        start = datetime.fromisoformat(start_str) if start_str else datetime.now(UTC)
        end = datetime.fromisoformat(end_str) if end_str else start

        return Journal(
            id=journal_id,
            user_id=journal_data["user_id"],
            title=journal_data.get("title", ""),
            content=journal_data.get("content", ""),
            event_date_range=EventDateRange(start=start, end=end),
        )

    async def _save_calendar_info(
        self, journal_id: int, calendar_info_data: dict[str, Any]
    ) -> None:
        """Save calendar info for a journal using raw SQL."""
        calendar_id = UUID(calendar_info_data["calendar_id"])

        start_time = self._parse_time(calendar_info_data.get("start_time"))
        end_time = self._parse_time(calendar_info_data.get("end_time"))

        await self.connection.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, location, start_time, end_time)
                VALUES
                    (:journal_id, :calendar_id, :is_all_day, :location, :start_time, :end_time)
                ON CONFLICT (journal_id) DO UPDATE SET
                    calendar_id = :calendar_id,
                    is_all_day = :is_all_day,
                    location = :location,
                    start_time = :start_time,
                    end_time = :end_time
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "is_all_day": calendar_info_data.get("is_all_day", False),
                "location": calendar_info_data.get("location"),
                "start_time": start_time,
                "end_time": end_time,
            },
        )

    @staticmethod
    def _parse_time(value: str | time | None) -> time | None:
        """Parse a time string (HH:MM:SS) into a datetime.time object."""
        if value is None:
            return None
        if isinstance(value, time):
            return value
        return time.fromisoformat(value)

    async def _create_external_event_link(
        self,
        journal_id: int,
        calendar_id: UUID,
        external_event_id: str,
        etag: str | None,
    ) -> None:
        """Create an external event link for tracking sync state."""
        now = datetime.now(UTC)
        await self.connection.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     external_version,
                     sync_capability, sync_status,
                     created_at, updated_at)
                VALUES
                    (:journal_id, :calendar_id, :external_event_id,
                     :etag,
                     'bidirectional', 'synced',
                     :now, :now)
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
                "etag": etag,
                "now": now,
            },
        )

    async def _find_journal_by_id(self, journal_id: int) -> Journal | None:
        """Find a journal by its ID using raw SQL."""
        result = await self.connection.execute(
            text("""
                SELECT id, user_id, title, content,
                       event_date_range_start, event_date_range_end,
                       parent_id, "order", created_at, updated_at
                FROM journals
                WHERE id = :journal_id
            """),
            {"journal_id": journal_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return Journal(
            id=row.id,
            user_id=row.user_id,
            title=row.title,
            content=row.content,
            event_date_range=EventDateRange(
                start=row.event_date_range_start,
                end=row.event_date_range_end,
            ),
            parent_id=row.parent_id,
            order=row.order,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _find_external_event_link(
        self,
        calendar_id: UUID,
        external_event_id: str,
    ) -> Any | None:
        """Find an existing external event link."""
        result = await self.connection.execute(
            text("""
                SELECT external_version, journal_id, sync_capability, sync_status
                FROM journal_external_event_links
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
            },
        )
        return result.fetchone()

    async def _update_external_event_link_etag(
        self,
        calendar_id: UUID,
        external_event_id: str,
        etag: str | None,
    ) -> None:
        """Update the ETag on an external event link after successful sync."""
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET external_version = :etag,
                    updated_at = :now,
                    sync_status = 'synced'
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "etag": etag,
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
                "now": datetime.now(UTC),
            },
        )
