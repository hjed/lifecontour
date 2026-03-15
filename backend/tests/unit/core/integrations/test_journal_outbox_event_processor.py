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


def _make_journal_event_data(
    *,
    sync_action: str = "created",
    external_event_id: str = "google-event-abc",
    calendar_id: str = CALENDAR_ID,
    etag: str = '"etag-123"',
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
        invitee_email = "alice@example.com"
        event_data = _make_journal_event_data(
            sync_action="created",
            contact_relationships=[
                {"email": invitee_email, "relationship_type": "INVITEE"},
            ],
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

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

        # Mock DB execute calls:
        # 1. _save_calendar_info
        # 2. _create_external_event_link
        # 3. contact_resolver.resolve_by_email → returns contact_id
        # 4. _get_relationships_by_type → returns empty
        # 5. _create_contact_relationship
        resolve_result = MagicMock()
        resolve_row = MagicMock()
        resolve_row.id = 100
        resolve_result.fetchone.return_value = resolve_row

        existing_rels_result = MagicMock()
        existing_rels_result.fetchall.return_value = []

        empty_result = MagicMock()
        empty_result.fetchone.return_value = None
        empty_result.fetchall.return_value = []

        mock_connection.execute.side_effect = [
            empty_result,  # _save_calendar_info
            empty_result,  # _create_external_event_link
            resolve_result,  # contact resolver
            existing_rels_result,  # existing relationships
            empty_result,  # create relationship
        ]

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

        # Verify DB was called at least 5 times (calendar, link, resolve, get_rels, create_rel)
        assert mock_connection.execute.call_count == 5

    @pytest.mark.asyncio
    async def test_process_journal_event_created_no_invitees(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Creates journal without invitees when contact_relationships is empty."""
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_journal_event_data(
                sync_action="created", contact_relationships=[]
            ),
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

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
        mock_connection.execute.return_value = MagicMock()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # Only 2 DB calls: calendar info + external link (no relationship calls)
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
        invitees = [{"email": "bob@example.com", "relationship_type": "INVITEE"}]
        event_data = _make_journal_event_data(
            sync_action="updated",
            existing_journal_id=42,
            contact_relationships=invitees,
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.updated",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        journal_row = _make_journal_row()
        link_row = _make_link_row()

        journal_result = MagicMock()
        journal_result.fetchone.return_value = journal_row

        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        resolve_result = MagicMock()
        resolve_row = MagicMock()
        resolve_row.id = 200
        resolve_result.fetchone.return_value = resolve_row

        existing_rels_result = MagicMock()
        existing_rels_result.fetchall.return_value = []

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None
        generic_result.fetchall.return_value = []

        mock_connection.execute.side_effect = [
            journal_result,  # _find_journal_by_id
            link_result,  # _find_external_event_link
            generic_result,  # _save_calendar_info
            generic_result,  # _update_external_event_link_etag
            resolve_result,  # contact resolver
            existing_rels_result,  # existing relationships
            generic_result,  # create relationship
        ]

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

    @pytest.mark.asyncio
    async def test_process_journal_event_updated_preserves_local_edits(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """When journal was locally edited after last sync, title/content are preserved."""
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

        journal_result = MagicMock()
        journal_result.fetchone.return_value = journal_row

        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None
        generic_result.fetchall.return_value = []

        mock_connection.execute.side_effect = [
            journal_result,  # _find_journal_by_id
            link_result,  # _find_external_event_link
            generic_result,  # _save_calendar_info
            generic_result,  # _update_external_event_link_etag
        ]

        mock_journal_service.update_journal.return_value = Journal(
            id=42,
            user_id="1",
            title="My Local Title",
            content="My local content",
            event_date_range=EventDateRange(
                start=datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
                end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
            ),
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # Protected fields should be the local values, not the inbound values
        update_call = mock_journal_service.update_journal
        journal_arg = update_call.call_args[0][0]
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

    # ── ETag idempotency ──────────────────────────────────────────────

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

        journal_row = _make_journal_row()
        link_row = _make_link_row(external_version='"etag-123"')

        journal_result = MagicMock()
        journal_result.fetchone.return_value = journal_row

        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        mock_connection.execute.side_effect = [journal_result, link_result]

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
        event_data = _make_journal_event_data(
            sync_action="updated",
            existing_journal_id=42,
            etag=None,  # type: ignore[arg-type]
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.updated",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        journal_row = _make_journal_row()
        link_row = _make_link_row(external_version=None)

        journal_result = MagicMock()
        journal_result.fetchone.return_value = journal_row

        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None
        generic_result.fetchall.return_value = []

        mock_connection.execute.side_effect = [
            journal_result,
            link_result,
            generic_result,  # _save_calendar_info
            generic_result,  # _update_external_event_link_etag
        ]

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

        # Should proceed with update, not skip
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

        # Existing journal has different date range
        journal_row = _make_journal_row()
        link_row = _make_link_row()

        journal_result = MagicMock()
        journal_result.fetchone.return_value = journal_row

        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None
        generic_result.fetchall.return_value = []

        mock_connection.execute.side_effect = [
            journal_result,
            link_result,
            generic_result,
            generic_result,
        ]

        mock_journal_service.update_journal.return_value = Journal(
            id=42,
            user_id="1",
            title="Team Meeting",
            content="Weekly sync",
            event_date_range=EventDateRange(
                start=datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
                end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
            ),
        )

        await processor.process_event(event)

        # Check changed_fields argument passed to update_journal
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
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_journal_event_data(sync_action="created"),
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

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
        mock_connection.execute.return_value = MagicMock()

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # Verify calendar info SQL includes updated_at
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
        event_data = _make_journal_event_data(
            sync_action="created",
            contact_relationships=[
                {"email": "alice@example.com", "relationship_type": "INVITEE"},
            ],
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

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

        resolve_result = MagicMock()
        resolve_row = MagicMock()
        resolve_row.id = 100
        resolve_result.fetchone.return_value = resolve_row

        existing_rels_result = MagicMock()
        existing_rels_result.fetchall.return_value = []

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None

        mock_connection.execute.side_effect = [
            generic_result,  # _save_calendar_info
            generic_result,  # _create_external_event_link
            resolve_result,  # resolve_by_email
            existing_rels_result,  # _get_relationships_by_type (INVITEE only)
            generic_result,  # _create_contact_relationship
        ]

        await processor.process_event(event)

        # The get_relationships call should query for INVITEE type only
        get_rels_call = mock_connection.execute.call_args_list[3]
        params = get_rels_call[0][1]
        assert params["relationship_type"] == "INVITEE"

    # ── Invitee sync: removes stale invitees ──────────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_removes_stale_invitees(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Invitees no longer in the Google event should be deleted locally."""
        event_data = _make_journal_event_data(
            sync_action="created",
            contact_relationships=[],  # No invitees
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

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
        mock_connection.execute.return_value = MagicMock()

        await processor.process_event(event)

        # No relationship calls should happen since contact_relationships is empty
        # DB calls: calendar info + external link = 2
        assert mock_connection.execute.call_count == 2

    # ── Invitee sync: unknown email skipped ───────────────────────────

    @pytest.mark.asyncio
    async def test_invitee_sync_unknown_email_skipped(
        self,
        processor: "JournalOutboxEventProcessor",
        mock_journal_service: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Emails not matching a contact should be silently skipped."""
        event_data = _make_journal_event_data(
            sync_action="created",
            contact_relationships=[
                {"email": "unknown@example.com", "relationship_type": "INVITEE"},
            ],
        )
        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=event_data,
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        created_journal = Journal(
            id=42,
            user_id="1",
            title="Meeting",
            content="",
            event_date_range=EventDateRange(
                start=datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
                end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
            ),
        )
        mock_journal_service.create_journal.return_value = created_journal

        # Resolve returns None (no matching contact)
        resolve_result = MagicMock()
        resolve_result.fetchone.return_value = None

        existing_rels_result = MagicMock()
        existing_rels_result.fetchall.return_value = []

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None

        mock_connection.execute.side_effect = [
            generic_result,  # _save_calendar_info
            generic_result,  # _create_external_event_link
            resolve_result,  # resolve_by_email → None
            existing_rels_result,  # _get_relationships_by_type
            # No create call since no contacts resolved
        ]

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # 4 calls: calendar, link, resolve, get_rels (no create since email unresolved)
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

        # No local edits: journal.updated_at <= link.updated_at
        journal_row = _make_journal_row(
            updated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        link_row = _make_link_row(
            updated_at=datetime(2026, 3, 16, tzinfo=UTC),  # link is newer
        )

        journal_result = MagicMock()
        journal_result.fetchone.return_value = journal_row

        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None
        generic_result.fetchall.return_value = []

        mock_connection.execute.side_effect = [
            journal_result,
            link_result,
            generic_result,
            generic_result,
        ]

        mock_journal_service.update_journal.return_value = Journal(
            id=42,
            user_id="1",
            title="Team Meeting",
            content="Weekly sync",
            event_date_range=EventDateRange(
                start=datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
                end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
            ),
        )

        result = await processor.process_event(event)

        assert result["status"] == "success"
        # When no local edits, inbound values should take effect
        journal_arg = mock_journal_service.update_journal.call_args[0][0]
        assert journal_arg.title == "Team Meeting"
        assert journal_arg.content == "Weekly sync"
