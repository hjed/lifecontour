"""
Unit tests for journal outbox event processing (inbound sync).

Tests the processing of journal_event.created and journal_event.updated
outbox events from integration workers, including invitee sync and
InboundFieldMerger protected-edit logic.
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

CALENDAR_ID = "12345678-1234-5678-1234-567812345678"

DEFAULT_DATE_RANGE = EventDateRange(
    start=datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
    end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
)


# ── Shared test helpers ──────────────────────────────────────────────


def _make_journal_event_data(
    *,
    sync_action: str = "created",
    external_event_id: str = "google-event-abc",
    calendar_id: str = CALENDAR_ID,
    etag: str | None = '"etag-123"',
    existing_journal_id: int | None = None,
    contact_relationships: list[dict[str, str]] | None = None,
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
        "contact_relationships": contact_relationships or [],
    }


def _make_outbox_event(
    event_type: str = "journal_event.created",
    **event_data_kwargs: Any,
) -> OutboxEvent:
    """Build an OutboxEvent with the given type and event_data overrides."""
    return OutboxEvent(
        id=uuid4(),
        event_type=event_type,
        event_data=_make_journal_event_data(**event_data_kwargs),
        created_at=datetime.now(UTC),
        processed_at=None,
        retry_count=0,
    )


def _make_journal(
    *,
    journal_id: int = 42,
    title: str = "Team Meeting",
    content: str = "Weekly sync",
) -> Journal:
    """Build a Journal domain object for mock return values."""
    return Journal(
        id=journal_id,
        user_id="1",
        title=title,
        content=content,
        event_date_range=DEFAULT_DATE_RANGE,
    )


def _make_journal_row(
    *,
    journal_id: int = 42,
    title: str = "Old Title",
    content: str = "Old content",
    updated_at: datetime | None = None,
) -> MagicMock:
    """Create a mock journal row for DB lookups."""
    row = MagicMock()
    row.id = journal_id
    row.user_id = "1"
    row.title = title
    row.content = content
    row.event_date_range_start = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
    row.event_date_range_end = datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
    row.parent_id = None
    row.order = None
    row.created_at = datetime(2026, 3, 1, tzinfo=UTC)
    row.updated_at = updated_at or datetime(2026, 3, 15, tzinfo=UTC)
    return row


def _make_link_row(
    *,
    external_version: str | None = '"etag-old"',
    updated_at: datetime | None = None,
) -> MagicMock:
    """Create a mock external event link row."""
    row = MagicMock()
    row.external_version = external_version
    row.journal_id = 42
    row.sync_capability = "bidirectional"
    row.sync_status = "synced"
    row.updated_at = updated_at or datetime(2026, 3, 16, tzinfo=UTC)
    return row


def _mock_resolve_contact(contact_id: int) -> MagicMock:
    """Build a mock DB result that resolves to the given contact_id."""
    result = MagicMock()
    row = MagicMock()
    row.id = contact_id
    result.fetchone.return_value = row
    return result


def _mock_empty_result() -> MagicMock:
    """Build a mock DB result with no rows."""
    result = MagicMock()
    result.fetchone.return_value = None
    result.fetchall.return_value = []
    return result


def _mock_empty_rels() -> MagicMock:
    """Build a mock DB result for an empty relationship query."""
    result = MagicMock()
    result.fetchall.return_value = []
    return result


def _mock_fetchone(row: MagicMock) -> MagicMock:
    """Wrap a mock row in a fetchone-returning result."""
    result = MagicMock()
    result.fetchone.return_value = row
    return result


# ── Tests ────────────────────────────────────────────────────────────


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
        """Creates a journal + calendar info + external link + synced invitees."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            contact_relationships=[
                {"email": "alice@example.com", "relationship_type": "INVITEE"},
            ],
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        mock_connection.execute.side_effect = [
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _create_external_event_link
            _mock_resolve_contact(100),  # contact resolver
            _mock_empty_rels(),  # existing relationships
            _mock_empty_result(),  # create relationship
        ]

        result = await processor.process_event(event)

        mock_journal_service.create_journal.assert_called_once()
        journal_arg = mock_journal_service.create_journal.call_args[0][0]
        assert journal_arg.title == "Team Meeting"
        assert journal_arg.content == "Weekly sync"

        assert result["status"] == "success"
        assert result["event_type"] == "journal_event.created"
        assert result["journal_id"] == 42
        assert mock_connection.execute.call_count == 5

    @pytest.mark.asyncio
    async def test_process_journal_event_created_no_invitees(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Creates journal without invitees when contact_relationships is empty."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            contact_relationships=[],
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.return_value = MagicMock()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # 2 DB calls: calendar info + external link (no relationship calls, no match detection)
        assert mock_connection.execute.call_count == 2

    # ── journal_event.updated ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Updates an existing journal with invitee sync."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            contact_relationships=[
                {"email": "bob@example.com", "relationship_type": "INVITEE"},
            ],
        )

        mock_connection.execute.side_effect = [
            _mock_fetchone(_make_journal_row()),  # _find_journal_by_id
            _mock_fetchone(_make_link_row()),  # _find_external_event_link
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
            _mock_resolve_contact(200),  # contact resolver
            _mock_empty_rels(),  # existing relationships
            _mock_empty_result(),  # create relationship
        ]

        mock_journal_service.update_journal.return_value = _make_journal()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["event_type"] == "journal_event.updated"
        assert result["journal_id"] == 42

    @pytest.mark.asyncio
    async def test_process_journal_event_updated_preserves_local_edits(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """When journal was locally edited after last sync, title/content are preserved."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
        )

        # Journal was updated AFTER the link's last sync
        journal_row = _make_journal_row(
            title="My Local Title",
            content="My local content",
            updated_at=datetime(2026, 3, 17, tzinfo=UTC),
        )
        link_row = _make_link_row(
            external_version='"etag-old"',
            updated_at=datetime(2026, 3, 16, tzinfo=UTC),  # earlier than journal
        )

        mock_connection.execute.side_effect = [
            _mock_fetchone(journal_row),  # _find_journal_by_id
            _mock_fetchone(link_row),  # _find_external_event_link
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        mock_journal_service.update_journal.return_value = _make_journal(
            title="My Local Title",
            content="My local content",
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        journal_arg = mock_journal_service.update_journal.call_args[0][0]
        assert journal_arg.title == "My Local Title"
        assert journal_arg.content == "My local content"
        # But date range should be from inbound (always-update field)
        assert journal_arg.event_date_range.start == datetime(
            2026, 3, 20, 10, 0, tzinfo=UTC
        )

    # ── journal_event.updated - missing journal ────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated_journal_not_found(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """When updated event references a non-existent journal_id, it should error."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=999,
        )

        mock_connection.execute.return_value = _mock_empty_result()

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
        event = _make_outbox_event(
            event_type="journal_event.conflicted",
            sync_action="conflicted",
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
        event = _make_outbox_event(event_type="journal_event.unknown")

        with pytest.raises(
            JournalOutboxEventProcessingError, match="Unknown journal event type"
        ):
            await processor.process_event(event)

    # ── ETag idempotency ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_idempotent_same_etag(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """If the ETag matches the stored external_version, skip processing."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            etag='"etag-123"',
        )

        mock_connection.execute.side_effect = [
            _mock_fetchone(_make_journal_row()),
            _mock_fetchone(_make_link_row(external_version='"etag-123"')),
        ]

        result = await processor.process_event(event)

        assert result["status"] == "skipped"
        assert result["reason"] == "etag_unchanged"
        mock_journal_service.update_journal.assert_not_called()

    @pytest.mark.asyncio
    async def test_etag_none_does_not_skip(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """None etag should NOT trigger idempotency skip, even when stored is also None."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            etag=None,
        )

        mock_connection.execute.side_effect = [
            _mock_fetchone(_make_journal_row()),
            _mock_fetchone(_make_link_row(external_version=None)),
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        mock_journal_service.update_journal.return_value = _make_journal()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        mock_journal_service.update_journal.assert_called_once()

    # ── Changed fields includes event_date_range ──────────────────────

    @pytest.mark.asyncio
    async def test_changed_fields_includes_date_range(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """event_date_range changes should be included in changed_fields."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
        )

        mock_connection.execute.side_effect = [
            _mock_fetchone(_make_journal_row()),
            _mock_fetchone(_make_link_row()),
            _mock_empty_result(),
            _mock_empty_result(),
        ]

        mock_journal_service.update_journal.return_value = _make_journal()

        await processor.process_event(event)

        changed_fields = mock_journal_service.update_journal.call_args[0][1]
        assert "event_date_range" in changed_fields

    # ── Calendar info upsert updated_at ───────────────────────────────

    @pytest.mark.asyncio
    async def test_calendar_info_upsert_updates_timestamp(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Calendar info upsert should include updated_at in ON CONFLICT clause."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.return_value = MagicMock()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        calendar_call = mock_connection.execute.call_args_list[0]
        sql_text = str(calendar_call[0][0].text)
        assert "updated_at" in sql_text

    # ── Invitee sync: only mutates INVITEE type ───────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_only_mutates_invitee_type(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Invitee sync should only touch INVITEE relationships, not PARTICIPANT."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            contact_relationships=[
                {"email": "alice@example.com", "relationship_type": "INVITEE"},
            ],
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        mock_connection.execute.side_effect = [
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _create_external_event_link
            _mock_resolve_contact(100),  # resolve_by_email
            _mock_empty_rels(),  # _get_relationships_by_type (INVITEE only)
            _mock_empty_result(),  # _create_contact_relationship
        ]

        await processor.process_event(event)

        # The get_relationships call should query for INVITEE type only
        get_rels_call = mock_connection.execute.call_args_list[3]
        params = get_rels_call[0][1]
        assert params["relationship_type"] == "INVITEE"

    # ── Invitee sync: removes stale invitees ──────────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_with_empty_list_clears_relationships(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """An empty invitee list should trigger clearing of existing INVITEE relationships."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            contact_relationships=[],  # Explicitly empty = clear invitees
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        # Mock execute for: _create_external_event_link, _save_calendar_info,
        # _get_relationships_by_type (returns empty = nothing to delete)
        mock_connection.execute.return_value = _mock_empty_rels()

        await processor.process_event(event)

        # With empty list [], _sync_contact_relationships should still run
        # (unlike None which would skip entirely). It queries for existing
        # INVITEE relationships and finds none, so no deletes needed.
        # Call count: _save_calendar_info + _create_external_event_link = 2 minimum
        assert mock_connection.execute.call_count >= 2

    # ── Invitee sync: unknown email skipped ───────────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_unknown_email_skipped(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Emails not matching a contact should be silently skipped."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            contact_relationships=[
                {"email": "unknown@example.com", "relationship_type": "INVITEE"},
            ],
        )

        mock_journal_service.create_journal.return_value = _make_journal(
            title="Meeting",
            content="",
        )

        resolve_no_match = MagicMock()
        resolve_no_match.fetchone.return_value = None

        mock_connection.execute.side_effect = [
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _create_external_event_link
            resolve_no_match,  # resolve_by_email → None
            _mock_empty_rels(),  # _get_relationships_by_type
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # 4 calls: calendar, link, resolve, get_rels (no create since email unresolved, no match detection)
        assert mock_connection.execute.call_count == 4

    # ── InboundFieldMerger applied during update ─────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated_uses_field_merger(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Verify that InboundFieldMerger is applied during update."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
        )

        # No local edits: journal.updated_at <= link.updated_at
        journal_row = _make_journal_row(
            updated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        link_row = _make_link_row(
            updated_at=datetime(2026, 3, 16, tzinfo=UTC),  # link is newer
        )

        mock_connection.execute.side_effect = [
            _mock_fetchone(journal_row),
            _mock_fetchone(link_row),
            _mock_empty_result(),
            _mock_empty_result(),
        ]

        mock_journal_service.update_journal.return_value = _make_journal()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # When no local edits, inbound values should take effect
        journal_arg = mock_journal_service.update_journal.call_args[0][0]
        assert journal_arg.title == "Team Meeting"
        assert journal_arg.content == "Weekly sync"


class TestJournalOutboxEventProcessorCancelled:
    """Tests for journal_event.cancelled processing."""

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        return AsyncMock(spec=AsyncConnection)

    @pytest.fixture
    def mock_journal_service(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def processor(
        self, mock_journal_service: AsyncMock, mock_connection: AsyncMock
    ) -> JournalOutboxEventProcessor:
        return JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
        )

    @pytest.mark.asyncio
    async def test_cancelled_event_updates_link_and_calendar_info(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """Cancelled event should update link sync_status and calendar_info event_state."""
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
        )

        mock_connection.execute.return_value = _mock_empty_result()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["event_type"] == "journal_event.cancelled"
        assert result["journal_id"] == 42

        # Should have called execute twice: once for link update, once for calendar_info update
        assert mock_connection.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_cancelled_event_without_journal_id_skips(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """Cancelled event without existing_journal_id should be skipped."""
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=None,
        )

        result = await processor.process_event(event)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_existing_journal_id"
        # Should not have called execute at all
        mock_connection.execute.assert_not_called()
