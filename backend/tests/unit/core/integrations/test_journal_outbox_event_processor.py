"""
Unit tests for journal outbox event processing (inbound sync).

Tests the processing of journal_event.created and journal_event.updated
outbox events from integration workers, including invitee sync and
InboundFieldMerger protected-edit logic.
"""

import inspect
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from core_shared.models.journal_external_event_link import (
    ExternalEventLinkSyncStatus,
)
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.journals.event_state import EventState
from core_shared.models.outbox import OutboxEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.journal_event_link_repository import (
    DeletionProtectionFacts,
    SeriesLinkedJournal,
)
from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessingError,
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.calendar_info_repository import _FIND_CANCELLED

CALENDAR_ID = "12345678-1234-5678-1234-567812345678"
SERIES_ID = uuid4()


def _mock(obj: object) -> AsyncMock:
    """View a mocked repository attribute as AsyncMock for configuration."""
    return cast(AsyncMock, obj)


def _make_mock_connection() -> AsyncMock:
    """AsyncConnection mock whose begin_nested() is awaitable.

    On the real class begin_nested is a sync method returning an awaitable
    AsyncTransaction, so the spec turns it into a plain MagicMock; the
    savepoint() helper needs `await connection.begin_nested()` to work.
    """
    conn = AsyncMock(spec=AsyncConnection)
    conn.begin_nested = AsyncMock()
    return conn


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
    recurring_event_id: str | None = None,
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
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "etag": etag,
        "existing_journal_id": existing_journal_id,
        "contact_relationships": contact_relationships or [],
        "recurring_event_id": recurring_event_id,
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
    recurring_event_id: str | None = None,
) -> MagicMock:
    """Create a mock external event link row."""
    row = MagicMock()
    row.external_version = external_version
    row.journal_id = 42
    row.sync_capability = "bidirectional"
    row.sync_status = "synced"
    row.updated_at = updated_at or datetime(2026, 3, 16, tzinfo=UTC)
    row.recurring_event_id = recurring_event_id
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
    ) -> JournalOutboxEventProcessor:
        return JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
            contact_repository=MagicMock(),
            strava_athlete_mapping_repository=MagicMock(),
        )

    # ── journal_event.created ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_created(
        self,
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link (idempotency check)
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
        assert mock_connection.execute.call_count == 7

    @pytest.mark.asyncio
    async def test_ensure_calendar_exists_called_with_correct_params(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """_ensure_calendar_exists should INSERT ON CONFLICT DO NOTHING with integration defaults."""
        from uuid import UUID

        strava_calendar_id = "00000000-0000-0000-0000-000000000001"
        event_data = _make_journal_event_data(
            sync_action="created",
            calendar_id=strava_calendar_id,
        )
        event_data["integration_source"] = "strava"
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        await processor.process_event(event)

        # First execute call should be _ensure_calendar_exists
        ensure_call = mock_connection.execute.call_args_list[0]
        sql_text = str(ensure_call[0][0].text)
        assert "INSERT INTO calendars" in sql_text
        assert "ON CONFLICT" in sql_text
        assert "DO NOTHING" in sql_text
        params = ensure_call[0][1]
        assert params["id"] == UUID(strava_calendar_id)
        assert params["name"] == "Strava Activities"
        assert params["color"] == "#FC4C02"

    @pytest.mark.asyncio
    async def test_process_journal_event_created_no_invitees(
        self,
        processor: JournalOutboxEventProcessor,
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
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # 3 DB calls: _find_external_event_link + calendar info + external link
        assert mock_connection.execute.call_count == 4

    # ── journal_event.updated ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated(
        self,
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),  # _find_journal_by_id
            _mock_fetchone(_make_link_row()),  # _find_external_event_link
            _mock_empty_result(),  # _find_calendar_info
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
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(journal_row),  # _find_journal_by_id
            _mock_fetchone(link_row),  # _find_external_event_link
            _mock_empty_result(),  # _find_calendar_info
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
        processor: JournalOutboxEventProcessor,
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
        processor: JournalOutboxEventProcessor,
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
        processor: JournalOutboxEventProcessor,
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
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
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
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),
            _mock_fetchone(_make_link_row(external_version=None)),
            _mock_empty_result(),  # _find_calendar_info
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        mock_journal_service.update_journal.return_value = _make_journal()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        mock_journal_service.update_journal.assert_called_once()

    # ── Date-range change drives the journal update ───────────────────

    @pytest.mark.asyncio
    async def test_date_range_change_passes_updated_journal_to_service(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """An inbound date-range change calls update_journal with the merged journal."""
        from core_shared.models.journals import Journal

        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),
            _mock_fetchone(_make_link_row()),
            _mock_empty_result(),  # _find_calendar_info
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        mock_journal_service.update_journal.return_value = _make_journal()

        await processor.process_event(event)

        mock_journal_service.update_journal.assert_called_once()
        passed_journal = mock_journal_service.update_journal.call_args[0][0]
        assert isinstance(passed_journal, Journal)
        assert passed_journal.event_date_range is not None
        assert mock_journal_service.update_journal.call_args[0][1] is mock_connection

    # ── Calendar info upsert updated_at ───────────────────────────────

    @pytest.mark.asyncio
    async def test_calendar_info_upsert_updates_timestamp(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Calendar info upsert should include updated_at in ON CONFLICT clause."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        # Add side_effect so it doesn't return MagicMock directly when _find_external_event_link is called
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"
        calendar_call = mock_connection.execute.call_args_list[2]
        sql_text = str(calendar_call[0][0].text)
        assert "updated_at" in sql_text

    # ── Invitee sync: only mutates INVITEE type ───────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_only_mutates_invitee_type(
        self,
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link (idempotency check)
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _create_external_event_link
            _mock_resolve_contact(100),  # resolve_by_email
            _mock_empty_rels(),  # _get_relationships_by_type (INVITEE only)
            _mock_empty_result(),  # _create_contact_relationship
        ]

        await processor.process_event(event)

        # The get_relationships call should query for INVITEE type only
        get_rels_call = mock_connection.execute.call_args_list[5]
        params = get_rels_call[0][1]
        assert params["relationship_type"] == "INVITEE"

    # ── Invitee sync: removes stale invitees ──────────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_with_empty_list_clears_relationships(
        self,
        processor: JournalOutboxEventProcessor,
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
        # Mock execute for: _find_external_event_link, _save_calendar_info, _create_external_event_link,
        # _get_relationships_by_type (returns empty = nothing to delete)
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),
            MagicMock(),
            MagicMock(),
            _mock_empty_rels(),
        ]

        await processor.process_event(event)

        # With empty list [], _sync_contact_relationships should still run
        # (unlike None which would skip entirely). It queries for existing
        # INVITEE relationships and finds none, so no deletes needed.
        # Call count: _find_external_event_link + _save_calendar_info + _create_external_event_link = 3 minimum
        assert mock_connection.execute.call_count >= 3

    # ── Invitee sync: unknown email skipped ───────────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_unknown_email_skipped(
        self,
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link (idempotency check)
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _create_external_event_link
            resolve_no_match,  # resolve_by_email → None
            _mock_empty_rels(),  # _get_relationships_by_type
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # 6 calls: ensure_calendar, find link, calendar, link, resolve, get_rels
        assert mock_connection.execute.call_count == 6

    # ── Invitee sync: handles role and status updates ─────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_handles_role_and_status_updates(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Sync should update status and role if they changed from existing."""

        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            contact_relationships=[
                {
                    "email": "update_me@example.com",
                    "relationship_type": "INVITEE",
                    "status": "ATTENDING",
                    "role": "ORGANISER",
                },
                {
                    "email": "demote_me@example.com",
                    "relationship_type": "INVITEE",
                    "status": "DECLINED",
                    "role": None,
                },
            ],
        )

        mock_journal_service.update_journal.return_value = _make_journal()

        def _mock_rels() -> MagicMock:
            result = MagicMock()
            row1 = MagicMock()
            row1.journal_id = 42
            row1.contact_id = 100
            row1.relationship_type = "INVITEE"
            row1.created_at = datetime(2026, 3, 1, tzinfo=UTC)
            row1.status = "NO_REPLY"  # Old status
            row1.role = None  # Did not have organiser

            row2 = MagicMock()
            row2.journal_id = 42
            row2.contact_id = 101
            row2.relationship_type = "INVITEE"
            row2.created_at = datetime(2026, 3, 1, tzinfo=UTC)
            row2.status = "ATTENDING"  # Same status
            row2.role = "ORGANISER"  # Had organiser, but inbound is None

            result.fetchall.return_value = [row1, row2]
            return result

        resolve_match = MagicMock()
        # Contact 100 is update_me, 101 is demote_me
        resolve_match.fetchone.side_effect = [MagicMock(id=100), MagicMock(id=101)]

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),  # find journal
            _mock_fetchone(_make_link_row()),  # find link
            _mock_empty_result(),  # _find_calendar_info
            _mock_empty_result(),  # save calendar info
            _mock_empty_result(),  # update etag
            resolve_match,  # resolve email 1 (update_me)
            resolve_match,  # resolve email 2 (demote_me)
            _mock_rels(),  # fetch existing
            _mock_empty_result(),  # update 1
            _mock_empty_result(),  # update 2
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"

        # Verify 2 updates occurred
        update_calls = [
            call
            for call in mock_connection.execute.call_args_list
            if "UPDATE journal_contact_relationships" in str(call[0][0].text)
        ]
        assert len(update_calls) == 2

        # Verify update 1 (100) set ORGANISER and ATTENDING
        params1 = update_calls[0][0][1]
        assert params1["contact_id"] == 100
        assert params1["status"] == "ATTENDING"
        assert params1["role"] == "ORGANISER"

        # Verify update 2 (101) demoted ORGANISER to None
        params2 = update_calls[1][0][1]
        assert params2["contact_id"] == 101
        assert params2["status"] == "DECLINED"
        assert params2["role"] is None

    # ── InboundFieldMerger applied during update ─────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated_uses_field_merger(
        self,
        processor: JournalOutboxEventProcessor,
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
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(journal_row),
            _mock_fetchone(link_row),
            _mock_empty_result(),  # _find_calendar_info
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        mock_journal_service.update_journal.return_value = _make_journal()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # When no local edits, inbound values should take effect
        journal_arg = mock_journal_service.update_journal.call_args[0][0]
        assert journal_arg.title == "Team Meeting"
        assert journal_arg.content == "Weekly sync"

    # ── private_description blocks inbound content ────────────────────

    @pytest.mark.asyncio
    async def test_process_journal_event_updated_private_description_blocks_content(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """When private_description is True, inbound content should be ignored."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
        )

        journal_row = _make_journal_row(
            title="Old Title",
            content="My private notes",
        )
        link_row = _make_link_row()

        # Mock _find_calendar_info returning a row with private_description=True
        calendar_info_row = MagicMock()
        calendar_info_row.private_description = True
        calendar_info_result = MagicMock()
        calendar_info_result.fetchone.return_value = calendar_info_row

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(journal_row),  # _find_journal_by_id
            _mock_fetchone(link_row),  # _find_external_event_link
            calendar_info_result,  # _find_calendar_info (private_description=True)
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        mock_journal_service.update_journal.return_value = _make_journal(
            title="Team Meeting",
            content="My private notes",
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        journal_arg = mock_journal_service.update_journal.call_args[0][0]
        # Content should be preserved from existing journal, not overwritten by inbound
        assert journal_arg.content == "My private notes"
        # Title should still take inbound value (not protected by private_description)
        assert journal_arg.title == "Team Meeting"


class TestJournalOutboxEventProcessorCancelled:
    """Tests for journal_event.cancelled processing."""

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        return _make_mock_connection()

    @pytest.fixture
    def mock_journal_service(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def processor(
        self, mock_journal_service: AsyncMock, mock_connection: AsyncMock
    ) -> JournalOutboxEventProcessor:
        proc = JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
            contact_repository=MagicMock(),
            strava_athlete_mapping_repository=MagicMock(),
        )
        # No link/journal facts: the recurring-deletion path stays inert and
        # the legacy mark-cancelled behaviour is what's under test here.
        proc.link_repo = AsyncMock()
        _mock(proc.link_repo).find_by_external_event.return_value = None
        return proc

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

    @pytest.mark.asyncio
    async def test_cancelled_event_state_is_bound_from_the_enum(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """The state written comes from ``EventState``, not a typed-out string.

        This write is one half of a contract whose other half —
        ``find_cancelled_journal_ids`` — already compares against the enum's
        value for the stated reason that renaming the member must not leave a
        query silently matching nothing. A literal here is the same hazard
        pointing the other way, and it is the hazard that matters more: a write
        that drifts leaves every task whose due journal was cancelled quietly
        un-lapsed, with nothing failing.
        """
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
        )
        mock_connection.execute.return_value = _mock_empty_result()

        await processor.process_event(event)

        statement, params = mock_connection.execute.call_args_list[1].args
        assert params["event_state"] == EventState.CANCELLED.value
        # Bound rather than inlined, which is what makes the assertion above
        # about the code's behaviour and not about this test's own string.
        assert "'cancelled'" not in str(statement)

    @pytest.mark.asyncio
    async def test_the_state_written_is_the_state_the_lapse_read_matches_on(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """The two ends of the cancellation contract, compared to each other.

        A task lapses with ``DUE_JOURNAL_CANCELLED`` only if the string the sync
        writes is the string ``CalendarInfoRepository`` looks for. Asserting each
        end against ``EventState`` separately would let both drift together;
        this reads the value out of the *compiled* query, so the comparison is
        against what that end actually sends to PostgreSQL.
        """
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
        )
        mock_connection.execute.return_value = _mock_empty_result()

        await processor.process_event(event)

        _, params = mock_connection.execute.call_args_list[1].args
        assert params["event_state"] == _FIND_CANCELLED.compile().params["cancelled"]

    @pytest.mark.asyncio
    async def test_cancelled_sync_status_is_bound_from_the_enum(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """The link's status is a decision input too, so it gets the same care.

        ``_should_delete_cancelled_instance`` checks this value **first**: a
        link already cancelled keeps its earlier keep decision, because marking
        a journal cancelled bumps the link's ``updated_at`` and erases the
        edit-protection signal. A literal that drifted from the enum on either
        side would let a redelivered cancellation delete a journal that was
        deliberately protected on the first pass — a data-loss bug with nothing
        failing to announce it.
        """
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
        )
        mock_connection.execute.return_value = _mock_empty_result()

        await processor.process_event(event)

        statement, params = mock_connection.execute.call_args_list[0].args
        assert params["sync_status"] == ExternalEventLinkSyncStatus.CANCELLED.value
        assert "'cancelled'" not in str(statement)

    def test_the_sticky_cancellation_guard_reads_the_same_enum(self) -> None:
        """The guard's comparison and the write above must not drift apart.

        Asserted against the guard's *source* rather than by running it, because
        the behaviour it protects only shows up on a second delivery of the same
        event — which the integration suite covers, but which cannot tell a
        matching pair of literals from a matching pair of enum references.
        """
        source = inspect.getsource(
            JournalOutboxEventProcessor._should_delete_cancelled_instance
        )
        assert "ExternalEventLinkSyncStatus.CANCELLED.value" in source
        assert '== "cancelled"' not in source


class TestStravaFitnessDataProcessing:
    """Tests for Strava-specific fitness data and journal type handling."""

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
        self, mock_journal_service: AsyncMock, mock_connection: AsyncMock
    ) -> JournalOutboxEventProcessor:
        return JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
            contact_repository=MagicMock(),
            strava_athlete_mapping_repository=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_created_event_saves_fitness_data(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Strava-sourced created event should persist fitness data via repository."""
        event_data = _make_journal_event_data(
            sync_action="created",
            external_event_id="strava-12345",
        )
        event_data["journal_data"]["fitness_data"] = {
            "distance": 10000,
            "elevation_gain": 200,
            "elevation_loss": 180,
            "duration": 3600,
            "calories": 500,
            "heart_rate_avg": 145,
            "heart_rate_max": 175,
            "strava_activity_id": "12345",
        }
        event_data["journal_data"]["journal_types"] = [
            "jogging",
            "fitness",
        ]

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        # Mock the fitness data repository save via the connection
        # The repository uses connection.execute internally with UPSERT SQL
        fitness_upsert_result = MagicMock()
        fitness_upsert_result.fetchone.return_value = MagicMock(
            journal_id=1,
            heart_rate_avg=145,
            heart_rate_max=175,
            distance=10000,
            elevation_gain=200,
            elevation_loss=180,
            duration=3600,
            calories=500,
            strava_activity_id="12345",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert_result,  # SqlFitnessDataRepository.save UPSERT
            MagicMock(),  # _ensure_type_data_rows: jogging INSERT
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"

        # Verify the fitness data repository was called (the UPSERT SQL)
        fitness_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "journal_fitness_data" in str(c[0][0].text)
        ]
        assert len(fitness_calls) >= 1, "Expected fitness data UPSERT call"
        params = fitness_calls[0][0][1]
        assert params["distance"] == 10000
        assert params["strava_activity_id"] == "12345"
        assert params["heart_rate_avg"] == 145

        # Verify journal types were added via the service
        assert mock_journal_service.add_type_to_journal.call_count == 2

    @pytest.mark.asyncio
    async def test_created_event_saves_journal_types_via_service(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Strava-sourced created event should add types via JournalService."""
        from core_shared.models.journals.journal_types import JournalType

        event_data = _make_journal_event_data(
            sync_action="created",
            external_event_id="strava-67890",
        )
        event_data["journal_data"]["journal_types"] = [
            "bushwalking",
            "outdoor_activity",
            "fitness",
        ]

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            MagicMock(),  # _ensure_type_data_rows: bushwalking INSERT
            MagicMock(),  # _ensure_type_data_rows: outdoor_activity INSERT
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # Verify add_type_to_journal was called for each type
        assert mock_journal_service.add_type_to_journal.call_count == 3

        added_types = [
            call.kwargs["journal_type"]
            for call in mock_journal_service.add_type_to_journal.call_args_list
        ]
        assert JournalType.BUSHWALKING in added_types
        assert JournalType.OUTDOOR_ACTIVITY in added_types
        assert JournalType.FITNESS in added_types

    @pytest.mark.asyncio
    async def test_created_event_without_fitness_data_skips(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Google Calendar events (no fitness_data) should not attempt to save fitness data."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            contact_relationships=[],
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # No fitness data or type calls expected
        assert mock_connection.execute.call_count == 4
        mock_journal_service.add_type_to_journal.assert_not_called()

    @pytest.mark.asyncio
    async def test_created_event_with_invalid_fitness_data_type_skips(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Non-dict fitness_data should be safely skipped."""
        event_data = _make_journal_event_data(
            sync_action="created",
            external_event_id="strava-bad",
        )
        event_data["journal_data"]["fitness_data"] = "not a dict"

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"
        # No fitness data SQL should have been called
        assert mock_connection.execute.call_count == 4

    @pytest.mark.asyncio
    async def test_created_event_with_unknown_journal_type_logs_warning(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Unknown journal type strings should be skipped with a warning, not crash."""
        event_data = _make_journal_event_data(
            sync_action="created",
            external_event_id="strava-unknown",
        )
        event_data["journal_data"]["journal_types"] = [
            "fitness",
            "unknown_type_xyz",
        ]

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # Only "fitness" should have been processed (unknown_type_xyz skipped)
        assert mock_journal_service.add_type_to_journal.call_count == 1

    @pytest.mark.asyncio
    async def test_created_event_creates_type_data_rows_for_activity_types(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Strava event with bushwalking/outdoor_activity types should INSERT data rows."""
        event_data = _make_journal_event_data(
            sync_action="created",
            external_event_id="strava-hike-001",
        )
        event_data["journal_data"]["fitness_data"] = {
            "distance": 15000,
            "elevation_gain": 500,
            "duration": 7200,
            "strava_activity_id": "hike001",
        }
        event_data["journal_data"]["journal_types"] = [
            "bushwalking",
            "outdoor_activity",
            "fitness",
        ]

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=42,
            distance=15000,
            elevation_gain=500,
            elevation_loss=None,
            duration=7200,
            calories=None,
            heart_rate_avg=None,
            heart_rate_max=None,
            strava_activity_id="hike001",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # SqlFitnessDataRepository.save
            MagicMock(),  # _ensure_type_data_rows: bushwalking INSERT
            MagicMock(),  # _ensure_type_data_rows: outdoor_activity INSERT
            # fitness is skipped (not in _TYPE_DATA_TABLE_MAP)
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # Find all INSERT calls targeting type-specific data tables
        type_data_inserts = [
            c
            for c in mock_connection.execute.call_args_list
            if "ON CONFLICT (journal_id) DO NOTHING" in str(c[0][0].text)
        ]
        assert len(type_data_inserts) == 2, (
            f"Expected 2 type data INSERT calls (bushwalking, outdoor_activity), "
            f"got {len(type_data_inserts)}"
        )

        # Verify the correct tables were targeted
        insert_sqls = [str(c[0][0].text) for c in type_data_inserts]
        assert any("journal_bushwalking_data" in sql for sql in insert_sqls), (
            "Missing bushwalking data INSERT"
        )
        assert any("journal_outdoor_activity_data" in sql for sql in insert_sqls), (
            "Missing outdoor_activity data INSERT"
        )

    @pytest.mark.asyncio
    async def test_created_event_does_not_create_duplicate_fitness_data_row(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """FITNESS type should NOT get a second INSERT via _ensure_type_data_rows."""
        event_data = _make_journal_event_data(
            sync_action="created",
            external_event_id="strava-run-001",
        )
        event_data["journal_data"]["fitness_data"] = {
            "distance": 5000,
            "elevation_gain": 50,
            "duration": 1800,
            "strava_activity_id": "run001",
        }
        # Only fitness type — no activity-specific types
        event_data["journal_data"]["journal_types"] = ["fitness"]

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=42,
            distance=5000,
            elevation_gain=50,
            elevation_loss=None,
            duration=1800,
            calories=None,
            heart_rate_avg=None,
            heart_rate_max=None,
            strava_activity_id="run001",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # SqlFitnessDataRepository.save
            # No _ensure_type_data_rows calls expected (fitness not in map)
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # Verify no ON CONFLICT DO NOTHING calls (only the fitness UPSERT via repo)
        type_data_inserts = [
            c
            for c in mock_connection.execute.call_args_list
            if "ON CONFLICT (journal_id) DO NOTHING" in str(c[0][0].text)
        ]
        assert len(type_data_inserts) == 0, (
            "FITNESS should not produce a type data row INSERT"
        )

    @pytest.mark.asyncio
    async def test_created_event_with_pydantic_validation_error_skips(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Malformed fitness_data dict that fails Pydantic validation should skip, not crash."""
        event_data = _make_journal_event_data(
            sync_action="created",
            external_event_id="strava-malformed",
        )
        # distance should be int|None, a string will fail Pydantic validation
        event_data["journal_data"]["fitness_data"] = {
            "distance": "not-a-number",
        }

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"
        # No fitness data UPSERT should have been called
        assert mock_connection.execute.call_count == 4


def _make_strava_event_data(
    *,
    sync_action: str = "created",
    strava_activity_id: str = "12345",
    gpx_xml: str | None = None,
    version_hash: str = "a" * 64,
    existing_journal_id: int | None = None,
) -> dict[str, Any]:
    """Build a sample Strava-sourced journal_event outbox payload."""
    return {
        "journal_data": {
            "title": "Morning Run",
            "content": "Easy jog",
            "event_date_range_start": "2026-03-20T08:00:00+00:00",
            "event_date_range_end": "2026-03-20T09:00:00+00:00",
            "user_id": "1",
            "fitness_data": {
                "distance": 10000,
                "elevation_gain": 150,
                "elevation_loss": 10,
                "duration": 3400,
                "calories": 500,
                "heart_rate_avg": 145,
                "heart_rate_max": 175,
                "strava_activity_id": strava_activity_id,
            },
            "journal_types": ["jogging", "fitness"],
            "gpx_xml": gpx_xml,
            "version_hash": version_hash,
        },
        "calendar_info_data": {
            "calendar_id": CALENDAR_ID,
            "is_all_day": False,
            "location": None,
            "start_time": "08:00:00",
            "end_time": "09:00:00",
        },
        "integration_source": "strava",
        "external_event_id": f"strava:{strava_activity_id}",
        "calendar_id": CALENDAR_ID,
        "sync_action": sync_action,
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "etag": None,
        "existing_journal_id": existing_journal_id,
        "contact_relationships": [],
    }


class TestGPXRouteAndSyncMetadata:
    """Tests for GPX→Route creation and SyncMetadata persistence in the processor."""

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        conn = AsyncMock(spec=AsyncConnection)
        conn.execute = AsyncMock()
        return conn

    @pytest.fixture
    def mock_journal_service(self) -> AsyncMock:
        from app.core.journal.services.journal_service import JournalService

        return AsyncMock(spec=JournalService)

    @pytest.fixture
    def processor(
        self, mock_journal_service: AsyncMock, mock_connection: AsyncMock
    ) -> JournalOutboxEventProcessor:
        return JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
            contact_repository=MagicMock(),
            strava_athlete_mapping_repository=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_persist_route_from_gpx_creates_route(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """When gpx_xml is present in journal_data, a Route row is inserted."""
        gpx_xml = '<?xml version="1.0"?><gpx><trk><trkseg><trkpt lat="-33.8" lon="151.2"></trkpt></trkseg></trk></gpx>'
        event_data = _make_strava_event_data(gpx_xml=gpx_xml)
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=42,
            distance=10000,
            elevation_gain=150,
            elevation_loss=10,
            duration=3400,
            calories=500,
            heart_rate_avg=145,
            heart_rate_max=175,
            strava_activity_id="12345",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # fitness data save
            MagicMock(),  # _ensure_type_data_rows: jogging INSERT
            _mock_empty_result(),  # _persist_route_from_gpx (SELECT existing)
            MagicMock(),  # _persist_route_from_gpx (INSERT route)
            MagicMock(),  # _persist_sync_metadata (UPSERT sync_metadata)
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # Find the route INSERT call
        route_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "routes" in str(c[0][0].text) and "INSERT" in str(c[0][0].text).upper()
        ]
        assert len(route_calls) >= 1, "Expected route INSERT call"
        params = route_calls[0][0][1]
        assert params["gpx_data"] == gpx_xml
        assert params["journal_id"] == 42
        assert params["name"] == "Morning Run"

    @pytest.mark.asyncio
    async def test_persist_route_skips_when_no_gpx(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """When gpx_xml is None, no Route row is created."""
        event_data = _make_strava_event_data(gpx_xml=None)
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=42,
            distance=10000,
            elevation_gain=150,
            elevation_loss=10,
            duration=3400,
            calories=500,
            heart_rate_avg=145,
            heart_rate_max=175,
            strava_activity_id="12345",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # fitness data save
            MagicMock(),  # _ensure_type_data_rows: jogging INSERT
            MagicMock(),  # _persist_sync_metadata
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # No route INSERT should exist
        route_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "routes" in str(c[0][0].text)
        ]
        assert len(route_calls) == 0, "No route INSERT expected when gpx_xml is None"

    @pytest.mark.asyncio
    async def test_persist_sync_metadata_for_strava(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Strava events should create a SyncMetadata record."""
        version_hash = "b" * 64
        event_data = _make_strava_event_data(
            version_hash=version_hash, strava_activity_id="99999"
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal()

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=42,
            distance=10000,
            elevation_gain=150,
            elevation_loss=10,
            duration=3400,
            calories=500,
            heart_rate_avg=145,
            heart_rate_max=175,
            strava_activity_id="99999",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # fitness data save
            MagicMock(),  # _ensure_type_data_rows: jogging INSERT
            MagicMock(),  # _persist_sync_metadata
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # Find SyncMetadata UPSERT call
        sync_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "sync_metadata" in str(c[0][0].text)
        ]
        assert len(sync_calls) >= 1, "Expected sync_metadata UPSERT call"
        params = sync_calls[0][0][1]
        assert params["integration_source"] == "strava"
        assert params["external_id"] == "99999"
        assert params["version_hash"] == version_hash
        assert params["internal_id"] == 42

    @pytest.mark.asyncio
    async def test_persist_sync_metadata_skips_for_google(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Google Calendar events should NOT create SyncMetadata."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            contact_relationships=[],
        )

        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)
        assert result["status"] == "success"

        # No sync_metadata calls expected
        sync_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "sync_metadata" in str(c[0][0].text)
        ]
        assert len(sync_calls) == 0, "No sync_metadata call expected for Google events"


class TestStravaMatchDetectionEmission:
    """Tests that Strava-sourced journal creation correctly emits match detection events.

    Verifies that when match_candidate_detector is wired (Gemini configured),
    the processor emits a `journal_review.detect_matches` outbox event for
    Strava journals, ensuring parity with the Google Calendar flow.
    """

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        conn = AsyncMock(spec=AsyncConnection)
        conn.execute = AsyncMock()
        return conn

    @pytest.fixture
    def mock_journal_service(self) -> AsyncMock:
        from app.core.journal.services.journal_service import JournalService

        return AsyncMock(spec=JournalService)

    @pytest.fixture
    def mock_match_detector(self) -> MagicMock:
        """Provide a non-None match_candidate_detector to enable emission."""
        return MagicMock()

    @pytest.fixture
    def processor_with_detector(
        self,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
        mock_match_detector: MagicMock,
    ) -> JournalOutboxEventProcessor:
        return JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
            contact_repository=MagicMock(),
            strava_athlete_mapping_repository=MagicMock(),
            match_candidate_detector=mock_match_detector,
        )

    @pytest.fixture
    def processor_without_detector(
        self,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> JournalOutboxEventProcessor:
        return JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
            contact_repository=MagicMock(),
            strava_athlete_mapping_repository=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_strava_created_event_emits_match_detection_when_detector_wired(
        self,
        processor_with_detector: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Strava-sourced created event should emit journal_review.detect_matches when detector is wired."""
        event_data = _make_strava_event_data(sync_action="created")
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal(
            title="Morning Run", content="Easy jog"
        )

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=42,
            distance=10000,
            elevation_gain=150,
            elevation_loss=10,
            duration=3400,
            calories=500,
            heart_rate_avg=145,
            heart_rate_max=175,
            strava_activity_id="12345",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # fitness data save
            MagicMock(),  # _ensure_type_data_rows: jogging INSERT
            MagicMock(),  # _persist_sync_metadata
            MagicMock(),  # _save_outbox_event (match detection)
        ]

        result = await processor_with_detector.process_event(event)
        assert result["status"] == "success"

        # Find the match detection outbox INSERT call
        outbox_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "outbox_events" in str(c[0][0].text)
            and "INSERT" in str(c[0][0].text).upper()
        ]
        assert len(outbox_calls) >= 1, (
            "Expected outbox INSERT for match detection event"
        )

        # Verify the event type is correct
        params = outbox_calls[0][0][1]
        assert params["event_type"] == "journal_review.detect_matches"

    @pytest.mark.asyncio
    async def test_strava_created_event_skips_match_detection_when_no_detector(
        self,
        processor_without_detector: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Strava-sourced event should NOT emit match detection when detector is None."""
        event_data = _make_strava_event_data(sync_action="created")
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal(
            title="Morning Run", content="Easy jog"
        )

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=42,
            distance=10000,
            elevation_gain=150,
            elevation_loss=10,
            duration=3400,
            calories=500,
            heart_rate_avg=145,
            heart_rate_max=175,
            strava_activity_id="12345",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # fitness data save
            MagicMock(),  # _ensure_type_data_rows: jogging INSERT
            MagicMock(),  # _persist_sync_metadata
        ]

        result = await processor_without_detector.process_event(event)
        assert result["status"] == "success"

        # No outbox INSERT for match detection
        outbox_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "outbox_events" in str(c[0][0].text)
        ]
        assert len(outbox_calls) == 0, (
            "No match detection event should be emitted without detector"
        )

    @pytest.mark.asyncio
    async def test_strava_match_detection_event_contains_correct_data(
        self,
        processor_with_detector: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Match detection event should contain correct journal metadata from Strava."""
        event_data = _make_strava_event_data(sync_action="created")
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        mock_journal_service.create_journal.return_value = _make_journal(
            journal_id=99, title="Morning Run", content="Easy jog"
        )

        fitness_upsert = MagicMock()
        fitness_upsert.fetchone.return_value = MagicMock(
            journal_id=99,
            distance=10000,
            elevation_gain=150,
            elevation_loss=10,
            duration=3400,
            calories=500,
            heart_rate_avg=145,
            heart_rate_max=175,
            strava_activity_id="12345",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link
            MagicMock(),  # _save_calendar_info
            MagicMock(),  # _create_external_event_link
            fitness_upsert,  # fitness data save
            MagicMock(),  # _ensure_type_data_rows: jogging INSERT
            MagicMock(),  # _persist_sync_metadata
            MagicMock(),  # _save_outbox_event (match detection)
        ]

        result = await processor_with_detector.process_event(event)
        assert result["status"] == "success"

        # Find the match detection outbox INSERT call and verify payload
        import json

        outbox_calls = [
            c
            for c in mock_connection.execute.call_args_list
            if "outbox_events" in str(c[0][0].text)
            and "INSERT" in str(c[0][0].text).upper()
        ]
        assert len(outbox_calls) >= 1

        params = outbox_calls[0][0][1]
        event_payload = json.loads(params["event_data"])

        assert event_payload["journal_id"] == 99
        assert event_payload["user_id"] == "1"
        assert event_payload["journal_title"] == "Morning Run"
        assert event_payload["journal_content"] == "Easy jog"
        assert "event_date_range_start" in event_payload
        assert "event_date_range_end" in event_payload


# ── Journal series / recurring cancellation tests ────────────────────


def _make_linked_journal(
    *,
    journal_id: int = 42,
    user_id: str = "1",
    external_event_id: str | None = "google-event-abc",
    recurring_event_id: str | None = "master-1",
    days_until_start: float = 10.0,
    duration_hours: float | None = 1.0,
    edited: bool = False,
    link_sync_status: str = "synced",
) -> SeriesLinkedJournal:
    """Build a SeriesLinkedJournal row relative to the current time.

    ``edited=True`` makes the journal's updated_at newer than the link's,
    which marks it as locally modified (protected from deletion).
    ``duration_hours=None`` leaves the event without an end date.
    """
    now = datetime.now(UTC)
    start = now + timedelta(days=days_until_start)
    link_updated_at = now - timedelta(days=5)
    journal_updated_at = (
        link_updated_at + timedelta(hours=1)
        if edited
        else link_updated_at - timedelta(hours=1)
    )
    return SeriesLinkedJournal(
        journal_id=journal_id,
        user_id=user_id,
        external_event_id=external_event_id,
        recurring_event_id=recurring_event_id,
        link_sync_status=link_sync_status,
        link_updated_at=link_updated_at,
        journal_updated_at=journal_updated_at,
        event_date_range_start=start,
        event_date_range_end=(
            start + timedelta(hours=duration_hours)
            if duration_hours is not None
            else None
        ),
    )


_UNPROTECTED_FACTS = DeletionProtectionFacts(
    has_children=False,
    has_tags=False,
    has_manual_contact_relationships=False,
)


def _make_series_cancelled_event(
    *,
    calendar_id: str = CALENDAR_ID,
    recurring_event_id: str = "master-1",
) -> OutboxEvent:
    """Build a journal_event.series_cancelled outbox event."""
    return OutboxEvent(
        id=uuid4(),
        event_type="journal_event.series_cancelled",
        event_data={
            "integration_source": "google",
            "calendar_id": calendar_id,
            "recurring_event_id": recurring_event_id,
            "sync_timestamp": datetime.now(UTC).isoformat(),
        },
        created_at=datetime.now(UTC),
        retry_count=0,
    )


class _SeriesProcessorTestBase:
    """Shared fixtures for the series / recurring-cancellation test classes.

    The processor gets stubbed link/series repositories: deletion-protection
    facts default to unprotected, find_by_external_event to None, and series
    get-or-create to a series with SERIES_ID — tests override per scenario.
    """

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        return _make_mock_connection()

    @pytest.fixture
    def mock_journal_service(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def processor(
        self, mock_journal_service: AsyncMock, mock_connection: AsyncMock
    ) -> JournalOutboxEventProcessor:
        proc = JournalOutboxEventProcessor(
            journal_service=mock_journal_service,
            connection=mock_connection,
            contact_repository=MagicMock(),
            strava_athlete_mapping_repository=MagicMock(),
        )
        proc.link_repo = AsyncMock()
        proc.series_repo = AsyncMock()
        _mock(
            proc.link_repo
        ).get_deletion_protection_facts.return_value = _UNPROTECTED_FACTS
        _mock(proc.link_repo).find_by_external_event.return_value = None
        series = MagicMock()
        series.id = SERIES_ID
        _mock(proc.series_repo).get_or_create_by_recurrence.return_value = series
        return proc


class TestRecurringCancellationDeletesFutureInstances(_SeriesProcessorTestBase):
    """journal_event.cancelled for recurring instances: far-future deletion."""

    @pytest.mark.asyncio
    async def test_future_unedited_instance_is_deleted(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """A far-future, unedited recurring instance is deleted outright."""
        _mock(
            processor.link_repo
        ).find_by_external_event.return_value = _make_linked_journal()
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
            recurring_event_id="master-1",
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["action"] == "deleted"
        mock_journal_service.delete_journal.assert_awaited_once()
        assert mock_journal_service.delete_journal.call_args[0][0] == 42
        # Links removed first so JournalDeleted carries no external ids
        # (the event is already gone upstream — no outbound delete).
        _mock(processor.link_repo).delete_links_for_journal.assert_awaited_once_with(42)
        # No mark-cancelled SQL ran.
        mock_connection.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_recurring_id_from_link_row_when_payload_lacks_it(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
    ) -> None:
        """Backfilled link column supplies the recurring id for old payloads."""
        _mock(
            processor.link_repo
        ).find_by_external_event.return_value = _make_linked_journal()
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
            recurring_event_id=None,
        )

        result = await processor.process_event(event)

        assert result["action"] == "deleted"
        mock_journal_service.delete_journal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_locally_edited_instance_marked_cancelled(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """A locally-edited future instance is preserved and marked cancelled."""
        _mock(
            processor.link_repo
        ).find_by_external_event.return_value = _make_linked_journal(edited=True)
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
            recurring_event_id="master-1",
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        mock_journal_service.delete_journal.assert_not_called()
        # Falls back to the mark-cancelled writes (link + calendar_info).
        assert mock_connection.execute.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "facts",
        [
            DeletionProtectionFacts(
                has_children=True,
                has_tags=False,
                has_manual_contact_relationships=False,
            ),
            DeletionProtectionFacts(
                has_children=False,
                has_tags=True,
                has_manual_contact_relationships=False,
            ),
            DeletionProtectionFacts(
                has_children=False,
                has_tags=False,
                has_manual_contact_relationships=True,
            ),
            DeletionProtectionFacts(
                has_children=False,
                has_tags=False,
                has_manual_contact_relationships=False,
                has_type_data=True,
            ),
            DeletionProtectionFacts(
                has_children=False,
                has_tags=False,
                has_manual_contact_relationships=False,
                has_routes=True,
            ),
        ],
        ids=[
            "children",
            "tags",
            "manual-contact-relationship",
            "type-data",
            "route",
        ],
    )
    async def test_protected_instance_falls_back_to_cancel(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
        facts: DeletionProtectionFacts,
    ) -> None:
        """Children, tags or manual contact links protect a journal from deletion."""
        _mock(
            processor.link_repo
        ).find_by_external_event.return_value = _make_linked_journal()
        _mock(processor.link_repo).get_deletion_protection_facts.return_value = facts
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
            recurring_event_id="master-1",
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        mock_journal_service.delete_journal.assert_not_called()
        assert mock_connection.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_near_future_instance_marked_cancelled(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """An instance starting within a day keeps today's cancel behaviour."""
        _mock(
            processor.link_repo
        ).find_by_external_event.return_value = _make_linked_journal(
            days_until_start=0.5
        )
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
            recurring_event_id="master-1",
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        mock_journal_service.delete_journal.assert_not_called()
        assert mock_connection.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_non_recurring_event_marks_cancelled(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Non-recurring cancellations keep today's behaviour unchanged."""
        _mock(
            processor.link_repo
        ).find_by_external_event.return_value = _make_linked_journal(
            recurring_event_id=None
        )
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
            recurring_event_id=None,
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        mock_journal_service.delete_journal.assert_not_called()
        assert mock_connection.execute.call_count == 2


class TestSeriesCancelledFanOut(_SeriesProcessorTestBase):
    """journal_event.series_cancelled: fan-out over all linked journals."""

    @pytest.mark.asyncio
    async def test_deletes_future_cancels_near_skips_past(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Far-future instances are deleted, near ones cancelled, past skipped."""
        _mock(processor.link_repo).find_journals_for_series.return_value = [
            _make_linked_journal(journal_id=1, days_until_start=10),
            _make_linked_journal(journal_id=2, days_until_start=0.5),
            _make_linked_journal(journal_id=3, days_until_start=-10),
        ]

        result = await processor.process_event(_make_series_cancelled_event())

        assert result["status"] == "success"
        assert result["deleted"] == 1
        assert result["cancelled"] == 1
        assert result["skipped_past"] == 1
        mock_journal_service.delete_journal.assert_awaited_once()
        assert mock_journal_service.delete_journal.call_args[0][0] == 1
        # Journal 2 marked cancelled: link + calendar_info updates.
        assert mock_connection.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_edited_future_journal_preserved_as_cancelled(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """A locally-edited far-future instance is cancelled, not deleted."""
        _mock(processor.link_repo).find_journals_for_series.return_value = [
            _make_linked_journal(journal_id=1, days_until_start=10, edited=True),
        ]

        result = await processor.process_event(_make_series_cancelled_event())

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        mock_journal_service.delete_journal.assert_not_called()
        assert mock_connection.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_no_linked_journals_is_noop_success(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """A series with no linked journals succeeds without doing anything."""
        _mock(processor.link_repo).find_journals_for_series.return_value = []

        result = await processor.process_event(_make_series_cancelled_event())

        assert result["status"] == "success"
        assert result["deleted"] == 0
        assert result["cancelled"] == 0
        mock_journal_service.delete_journal.assert_not_called()
        mock_connection.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_on_one_journal_processes_rest_then_fails_event(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """A failing journal must not poison the rest of the fan-out, but the
        event must fail afterwards so the (idempotent) retry can pick up the
        journals that errored — a success ack would drop them forever."""
        _mock(processor.link_repo).find_journals_for_series.return_value = [
            _make_linked_journal(journal_id=1, days_until_start=10),
            _make_linked_journal(journal_id=2, days_until_start=0.5),
        ]
        mock_journal_service.delete_journal.side_effect = RuntimeError("boom")

        with pytest.raises(JournalOutboxEventProcessingError, match="1 of 2"):
            await processor.process_event(_make_series_cancelled_event())

        # Journal 2 was still attempted (marked cancelled) before the raise.
        assert mock_connection.execute.call_count == 2


class TestSeriesMembershipOnCreateAndUpdate(_SeriesProcessorTestBase):
    """Auto-linking synced recurring instances into a journal series."""

    @pytest.mark.asyncio
    async def test_created_event_with_recurring_id_ensures_series_membership(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Creating a journal from a recurring instance links it into a series."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
            recurring_event_id="master-1",
        )
        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link (idempotency check)
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _create_external_event_link
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"
        _mock(
            processor.series_repo
        ).get_or_create_by_recurrence.assert_awaited_once_with(
            user_id="1",
            calendar_id=UUID(CALENDAR_ID),
            recurring_event_id="master-1",
            name="Team Meeting",
        )
        _mock(processor.series_repo).add_member.assert_awaited_once_with(SERIES_ID, 42)

    @pytest.mark.asyncio
    async def test_created_event_without_recurring_id_skips_series(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Non-recurring events create no series."""
        event = _make_outbox_event(
            event_type="journal_event.created",
            sync_action="created",
        )
        mock_journal_service.create_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_empty_result(),  # _find_external_event_link (idempotency check)
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _create_external_event_link
        ]

        await processor.process_event(event)

        _mock(processor.series_repo).get_or_create_by_recurrence.assert_not_called()
        _mock(processor.series_repo).add_member.assert_not_called()

    @pytest.mark.asyncio
    async def test_updated_event_with_recurring_id_backfills_series_membership(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """An update carrying a recurring id backfills the link and series."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            etag='"etag-new"',
            recurring_event_id="master-1",
        )
        mock_journal_service.update_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),  # _find_journal_by_id
            _mock_fetchone(_make_link_row()),  # _find_external_event_link
            _mock_empty_result(),  # _find_calendar_info (private_description)
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"
        _mock(processor.series_repo).get_or_create_by_recurrence.assert_awaited_once()
        _mock(processor.series_repo).add_member.assert_awaited_once_with(SERIES_ID, 42)

    @pytest.mark.asyncio
    async def test_update_link_etag_persists_recurring_event_id(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """The link update SQL persists the recurring id (COALESCE keeps old)."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            etag='"etag-new"',
            recurring_event_id="master-1",
        )
        mock_journal_service.update_journal.return_value = _make_journal()
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),  # _find_journal_by_id
            _mock_fetchone(_make_link_row()),  # _find_external_event_link
            _mock_empty_result(),  # _find_calendar_info (private_description)
            _mock_empty_result(),  # _save_calendar_info
            _mock_empty_result(),  # _update_external_event_link_etag
        ]

        await processor.process_event(event)

        etag_update_call = mock_connection.execute.call_args_list[5]
        sql_text = str(etag_update_call[0][0].text)
        assert "recurring_event_id" in sql_text
        assert "COALESCE" in sql_text
        assert etag_update_call[0][1]["recurring_event_id"] == "master-1"


class TestSeriesCancelledFanOutRobustness(_SeriesProcessorTestBase):
    """PR-review hardening: nullable link/date fields in the fan-out."""

    @pytest.mark.asyncio
    async def test_link_without_external_id_still_marked_cancelled(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """The link UPDATE keys on (journal_id, calendar_id), not the
        nullable external_event_id (NULL = NULL is false in SQL)."""
        _mock(processor.link_repo).find_journals_for_series.return_value = [
            _make_linked_journal(
                journal_id=7, days_until_start=0.5, external_event_id=None
            ),
        ]

        result = await processor.process_event(_make_series_cancelled_event())

        assert result["cancelled"] == 1
        link_update_call = mock_connection.execute.call_args_list[0]
        sql_text = str(link_update_call[0][0].text)
        assert "journal_id = :journal_id" in sql_text
        assert "external_event_id" not in sql_text
        assert link_update_call[0][1]["journal_id"] == 7

    @pytest.mark.asyncio
    async def test_past_instance_without_end_date_is_skipped(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """With no end date, the past-event skip falls back to the start."""
        _mock(processor.link_repo).find_journals_for_series.return_value = [
            _make_linked_journal(
                journal_id=8, days_until_start=-10, duration_hours=None
            ),
        ]

        result = await processor.process_event(_make_series_cancelled_event())

        assert result["skipped_past"] == 1
        assert result["deleted"] == 0
        assert result["cancelled"] == 0
        mock_journal_service.delete_journal.assert_not_called()
        mock_connection.execute.assert_not_called()


class TestSeriesCancelledFanOutSavepoints(_SeriesProcessorTestBase):
    """PR-review hardening: each fan-out item runs in a SAVEPOINT so a
    failed item rolls back cleanly (per the batch-loop rule)."""

    @pytest.mark.asyncio
    async def test_failed_item_rolls_back_its_savepoint(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """A failing delete rolls back its item's savepoint (undoing the
        already-executed link deletion) while the next item commits."""
        _mock(processor.link_repo).find_journals_for_series.return_value = [
            _make_linked_journal(journal_id=1, days_until_start=10),
            _make_linked_journal(journal_id=2, days_until_start=0.5),
        ]
        mock_journal_service.delete_journal.side_effect = RuntimeError("boom")

        with pytest.raises(JournalOutboxEventProcessingError):
            await processor.process_event(_make_series_cancelled_event())

        # One savepoint per item: the failed delete rolled back, the
        # successful mark-cancelled committed.
        savepoint = mock_connection.begin_nested.return_value
        assert mock_connection.begin_nested.await_count == 2
        savepoint.rollback.assert_awaited_once()
        savepoint.commit.assert_awaited_once()


class TestUnchangedEtagBackfill(_SeriesProcessorTestBase):
    """Audit fix: the backfill must persist even when the ETag is unchanged.

    The worker's backfill promotion re-sends unchanged events with the SAME
    etag; if the etag-unchanged skip runs first, the recurring id is never
    stored and the worker re-promotes forever."""

    @pytest.mark.asyncio
    async def test_unchanged_etag_update_still_backfills_recurring_id_and_series(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """An etag-unchanged UPDATE with a new recurring id persists the link
        backfill and series membership before skipping."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            etag='"etag-old"',  # matches the stored link version
            recurring_event_id="master-1",
        )
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),  # _find_journal_by_id
            _mock_fetchone(
                _make_link_row(recurring_event_id=None)
            ),  # _find_external_event_link (same etag, unbackfilled)
            _mock_empty_result(),  # _update_external_event_link_etag (backfill)
        ]

        result = await processor.process_event(event)

        assert result["status"] == "skipped"
        assert result["reason"] == "etag_unchanged"
        backfill_call = mock_connection.execute.call_args_list[3]
        sql_text = str(backfill_call[0][0].text)
        assert "recurring_event_id" in sql_text
        assert backfill_call[0][1]["recurring_event_id"] == "master-1"
        _mock(processor.series_repo).get_or_create_by_recurrence.assert_awaited_once()
        _mock(processor.series_repo).add_member.assert_awaited_once_with(SERIES_ID, 42)

    @pytest.mark.asyncio
    async def test_unchanged_etag_update_with_stored_recurring_id_pure_skip(
        self,
        processor: JournalOutboxEventProcessor,
        mock_connection: AsyncMock,
    ) -> None:
        """Once backfilled, an etag-unchanged UPDATE does no writes at all."""
        event = _make_outbox_event(
            event_type="journal_event.updated",
            sync_action="updated",
            existing_journal_id=42,
            etag='"etag-old"',
            recurring_event_id="master-1",
        )
        mock_connection.execute.side_effect = [
            MagicMock(),  # _ensure_calendar_exists
            _mock_fetchone(_make_journal_row()),  # _find_journal_by_id
            _mock_fetchone(
                _make_link_row(recurring_event_id="master-1")
            ),  # _find_external_event_link (same etag, already backfilled)
        ]

        result = await processor.process_event(event)

        assert result["status"] == "skipped"
        assert mock_connection.execute.call_count == 3
        _mock(processor.series_repo).get_or_create_by_recurrence.assert_not_called()
        _mock(processor.series_repo).add_member.assert_not_called()


class TestStickyCancellationDecision(_SeriesProcessorTestBase):
    """PR-review hardening: a link already marked cancelled is never eligible
    for deletion on a later pass.

    _mark_journal_cancelled bumps the link's updated_at, which erases the
    journal_updated_at > link_updated_at edit signal — so on event redelivery
    (or a repeated upstream cancellation) a previously-protected, locally
    edited journal would otherwise look unedited and be deleted."""

    @pytest.mark.asyncio
    async def test_fan_out_never_deletes_an_already_cancelled_link(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
    ) -> None:
        """A far-future, seemingly-unedited journal whose link is already
        cancelled keeps the earlier keep decision on redelivery."""
        _mock(processor.link_repo).find_journals_for_series.return_value = [
            _make_linked_journal(
                journal_id=1, days_until_start=10, link_sync_status="cancelled"
            ),
        ]

        result = await processor.process_event(_make_series_cancelled_event())

        mock_journal_service.delete_journal.assert_not_called()
        assert result["deleted"] == 0
        assert result["cancelled"] == 1

    @pytest.mark.asyncio
    async def test_instance_cancellation_never_deletes_an_already_cancelled_link(
        self,
        processor: JournalOutboxEventProcessor,
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """The single-instance delete path applies the same sticky rule."""
        _mock(
            processor.link_repo
        ).find_by_external_event.return_value = _make_linked_journal(
            link_sync_status="cancelled"
        )
        event = _make_outbox_event(
            event_type="journal_event.cancelled",
            sync_action="cancelled",
            existing_journal_id=42,
            recurring_event_id="master-1",
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        mock_journal_service.delete_journal.assert_not_called()
        # Falls through to the (idempotent) mark-cancelled writes.
        assert mock_connection.execute.call_count == 2
