"""
Unit tests for journal outbox event processing (inbound sync).

Tests the processing of journal_event.created and journal_event.updated
outbox events from integration workers, following the same patterns as
the contact outbox event processor tests.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.outbox import OutboxEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessingError,
    JournalOutboxEventProcessor,
)


def _make_journal_event_data(
    *,
    sync_action: str = "created",
    external_event_id: str = "google-event-abc",
    calendar_id: str = "12345678-1234-5678-1234-567812345678",
    etag: str = '"etag-123"',
    existing_journal_id: int | None = None,
) -> dict[str, Any]:
    """Build a sample journal_event outbox payload."""
    return {
        "journal_data": {
            "title": "Team Meeting",
            "content": "Weekly sync",
            "event_date_range_start": "2026-03-20T10:00:00+00:00",
            "event_date_range_end": "2026-03-20T11:00:00+00:00",
            "user_id": "1",
        },
        "calendar_info_data": {
            "calendar_id": calendar_id,
            "is_all_day": False,
            "location": "Conference Room A",
            "start_time": "10:00:00",
            "end_time": "11:00:00",
        },
        "integration_source": "google",
        "external_event_id": external_event_id,
        "calendar_id": calendar_id,
        "sync_action": sync_action,
        "etag": etag,
        "existing_journal_id": existing_journal_id,
    }


class TestJournalOutboxEventProcessor:
    """Test cases for JournalOutboxEventProcessor."""

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        """Create mock database connection."""
        conn = AsyncMock(spec=AsyncConnection)
        conn.execute = AsyncMock()
        return conn

    @pytest.fixture
    def mock_journal_service(self) -> AsyncMock:
        """Create mock journal service."""
        from app.core.journal.services.journal_service import JournalService

        return AsyncMock(spec=JournalService)

    @pytest.fixture
    def processor(
        self,
        mock_connection: AsyncMock,
        mock_journal_service: AsyncMock,
    ) -> "JournalOutboxEventProcessor":
        return JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
        )

    # ── journal_event.created ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_created(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Creates a journal + calendar info + external event link for a new event."""
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_journal_event_data(sync_action="created"),
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        # Mock journal creation to return a journal with an ID
        created_journal = Journal(
            id=42,
            user_id="1",
            title="Team Meeting",
            content="Weekly sync",
            event_date_range=EventDateRange(
                start=datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
                end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
            ),
        )
        mock_journal_service.create_journal.return_value = created_journal

        # Mock DB calls for calendar info and external link
        mock_connection.execute.return_value = MagicMock()

        result = await processor.process_event(event)

        # Verify journal was created
        mock_journal_service.create_journal.assert_called_once()
        journal_arg = mock_journal_service.create_journal.call_args[0][0]
        assert journal_arg.title == "Team Meeting"
        assert journal_arg.content == "Weekly sync"

        # Verify result
        assert result["status"] == "success"
        assert result["event_type"] == "journal_event.created"
        assert result["journal_id"] == 42

    # ── journal_event.updated ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Updates an existing journal from an inbound event."""
        event_data = _make_journal_event_data(
            sync_action="updated",
            existing_journal_id=42,
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.updated",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        # Mock the DB lookup for the existing journal
        journal_row = MagicMock()
        journal_row.id = 42
        journal_row.user_id = "1"
        journal_row.title = "Old Title"
        journal_row.content = "Old content"
        journal_row.event_date_range_start = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
        journal_row.event_date_range_end = datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        journal_row.parent_id = None
        journal_row.order = None
        journal_row.created_at = datetime(2026, 3, 1, tzinfo=UTC)
        journal_row.updated_at = datetime(2026, 3, 15, tzinfo=UTC)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = journal_row
        mock_connection.execute.return_value = mock_result

        updated_journal = Journal(
            id=42,
            user_id="1",
            title="Team Meeting",
            content="Weekly sync",
            event_date_range=EventDateRange(
                start=datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
                end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
            ),
        )
        mock_journal_service.update_journal.return_value = updated_journal

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["event_type"] == "journal_event.updated"
        assert result["journal_id"] == 42

    # ── journal_event.updated - missing journal ────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated_journal_not_found(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """When updated event references a non-existent journal_id, it should error."""
        event_data = _make_journal_event_data(
            sync_action="updated",
            existing_journal_id=999,
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.updated",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        # Mock: journal not found
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        with pytest.raises(JournalOutboxEventProcessingError, match="not found"):
            await processor.process_event(event)

    # ── journal_event.conflicted ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_conflicted(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_connection: AsyncMock,
    ) -> None:
        """Conflicted events should mark the link as conflicted status."""
        event_data = _make_journal_event_data(sync_action="conflicted")
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.conflicted",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        mock_connection.execute.return_value = MagicMock()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["event_type"] == "journal_event.conflicted"

    # ── Unknown journal_event type ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_unknown_journal_event_type(
        self,
        processor: "JournalOutboxEventProcessor",
    ) -> None:
        """Unknown journal_event subtypes should raise an error."""
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.unknown",
            event_data=_make_journal_event_data(),
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        with pytest.raises(
            JournalOutboxEventProcessingError, match="Unknown journal event type"
        ):
            await processor.process_event(event)

    # ── Idempotency: same ETag skips processing ───────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_idempotent_same_etag(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """If the ETag matches the stored external_version, skip processing."""
        event_data = _make_journal_event_data(
            sync_action="updated",
            existing_journal_id=42,
            etag='"etag-123"',
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.updated",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        # Mock: journal exists
        journal_row = MagicMock()
        journal_row.id = 42
        journal_row.user_id = "1"
        journal_row.title = "Team Meeting"
        journal_row.content = "Weekly sync"
        journal_row.event_date_range_start = datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
        journal_row.event_date_range_end = datetime(2026, 3, 20, 11, 0, tzinfo=UTC)
        journal_row.parent_id = None
        journal_row.order = None
        journal_row.created_at = datetime(2026, 3, 1, tzinfo=UTC)
        journal_row.updated_at = datetime(2026, 3, 15, tzinfo=UTC)

        # Mock: link has the same etag
        link_row = MagicMock()
        link_row.external_version = '"etag-123"'

        journal_result = MagicMock()
        journal_result.fetchone.return_value = journal_row

        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        mock_connection.execute.side_effect = [journal_result, link_result]

        result = await processor.process_event(event)

        assert result["status"] == "skipped"
        assert result["reason"] == "etag_unchanged"
        mock_journal_service.update_journal.assert_not_called()
