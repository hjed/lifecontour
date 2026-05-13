"""Unit tests for sync_calendar_events ARQ task."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We need to import after setting up env vars (conftest handles this)


def _make_google_event(
    *,
    event_id: str = "google-event-1",
    summary: str = "Team Meeting",
    description: str = "Weekly sync",
    etag: str = '"etag-abc"',
    status: str = "confirmed",
    start_dt: str = "2026-03-20T10:00:00Z",
    end_dt: str = "2026-03-20T11:00:00Z",
) -> dict[str, Any]:
    """Build a raw Google Calendar event response dict."""
    return {
        "id": event_id,
        "summary": summary,
        "description": description,
        "etag": etag,
        "status": status,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
    }


TEST_CALENDAR_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _make_calendar_row(
    calendar_id: uuid.UUID = TEST_CALENDAR_UUID,
    google_calendar_id: str = "primary",
    is_synced_to_google: bool = True,
) -> MagicMock:
    """Build a mock calendar row from DB query."""
    row = MagicMock()
    row.calendar_id = calendar_id
    row.google_calendar_id = google_calendar_id
    row.is_synced_to_google = is_synced_to_google
    return row


class TestSyncCalendarEvents:
    """Tests for the sync_calendar_events ARQ task."""

    @pytest.fixture(autouse=True)
    def mock_metrics_collector(self):
        """Mock the metrics_collector with spec to catch API misuse."""
        from core_shared.metrics import MetricsCollector

        with patch("worker.metrics_collector", spec_set=MetricsCollector) as mock_mc:
            yield mock_mc

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session: AsyncMock) -> MagicMock:
        factory = MagicMock()
        factory.return_value = mock_session
        return factory

    @pytest.fixture
    def mock_ctx(self, mock_session_factory: MagicMock) -> dict[str, Any]:
        return {
            "session_factory": mock_session_factory,
            "redis": AsyncMock(),
        }

    @pytest.fixture
    def mock_google_client(self) -> MagicMock:
        client = MagicMock()
        client.list_events = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_sync_ignores_non_synced_calendars(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """When no calendars have is_synced_to_google=true, no events should be processed."""
        from worker import sync_calendar_events

        # Set up: query returns empty (no synced calendars)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = []
        mock_session.execute.return_value = cal_result

        with patch(
            "worker._create_google_client",
        ) as mock_create:
            mock_create.return_value = MagicMock()
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        assert result.get("events_processed", 0) == 0

    @pytest.mark.asyncio
    async def test_sync_creates_outbox_events_for_new_events(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """New events with no existing link should create journal_event.created outbox events."""
        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)

        # Calendar query
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]

        # Sync token query (none found)
        token_result = MagicMock()
        token_result.fetchone.return_value = None

        # Existing link lookup (none found for new event)
        link_result = MagicMock()
        link_result.fetchone.return_value = None

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            MagicMock(),  # sync token update
        ]

        google_events = {
            "items": [_make_google_event()],
            "nextSyncToken": "new-sync-token-123",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        assert result["events_processed"] >= 1
        # Verify outbox event was added to session
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_skips_unchanged_events(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Events with same ETag as stored should not create outbox events."""
        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)

        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]

        token_result = MagicMock()
        token_result.fetchone.return_value = None

        # Existing link with same ETag
        existing_link = MagicMock()
        existing_link.external_version = '"etag-abc"'
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 42
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        mock_session.execute.side_effect = [
            cal_result,
            token_result,
            link_result,
            MagicMock(),  # sync token save
        ]

        google_events = {
            "items": [_make_google_event(etag='"etag-abc"')],
            "nextSyncToken": "new-sync-token",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        # No outbox events should be created for unchanged event
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_updates_unchanged_events_if_new_contacts(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Events with same ETag should STILL be updated if a new contact match is found."""
        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]

        token_result = MagicMock()
        token_result.fetchone.return_value = None

        # Existing link with same ETag
        existing_link = MagicMock()
        existing_link.external_version = '"etag-abc"'
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 42
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        # Check result indicating a new contact matched
        check_result = MagicMock()
        check_result.fetchone.return_value = (
            1,
        )  # returning a row means new match found

        mock_session.execute.side_effect = [
            cal_result,
            token_result,
            link_result,
            check_result,
            MagicMock(),  # sync token save
        ]

        google_event_dict = _make_google_event(etag='"etag-abc"')
        google_event_dict["attendees"] = [{"email": "new.contact@example.com"}]
        google_events = {
            "items": [google_event_dict],
            "nextSyncToken": "new-sync-token",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        # Outbox event should be created for the unchanged event because check_result found a new contact
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_saves_calendar_sync_token(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """After successful sync, sync token should be saved to DB."""
        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]
        token_result = MagicMock()
        token_result.fetchone.return_value = None

        # No events to process
        mock_session.execute.side_effect = [
            cal_result,
            token_result,
            MagicMock(),  # sync token update
        ]

        google_events = {
            "items": [],
            "nextSyncToken": "saved-sync-token-xyz",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        # Verify the sync token was saved (session.execute called with update statement)
        execute_calls = mock_session.execute.call_args_list
        assert len(execute_calls) >= 3  # calendar query + token query + token save

    @pytest.mark.asyncio
    async def test_sync_falls_back_to_full_on_missing_token(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """When no token exists, should do full sync with time_min."""
        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]
        token_result = MagicMock()
        token_result.fetchone.return_value = None  # No sync token

        mock_session.execute.side_effect = [
            cal_result,
            token_result,
            MagicMock(),  # sync token save
        ]

        google_events = {
            "items": [],
            "nextSyncToken": "first-sync-token",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "smart"
            )

        assert result["status"] == "success"
        # list_events should have been called without sync_token (i.e., with time_min)
        call_kwargs = mock_client.list_events.call_args.kwargs
        assert "time_min" in call_kwargs
        assert "sync_token" not in call_kwargs

    @pytest.mark.asyncio
    async def test_sync_paginates_events(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Should follow nextPageToken until exhausted, collecting all events."""
        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]
        token_result = MagicMock()
        token_result.fetchone.return_value = None

        # Existing link lookup (none found) — used per event
        link_result = MagicMock()
        link_result.fetchone.return_value = None

        mock_session.execute.side_effect = [
            cal_result,
            token_result,
            link_result,  # link lookup for event on page 1
            link_result,  # link lookup for event on page 2
            MagicMock(),  # sync token save
        ]

        page_1 = {
            "items": [_make_google_event(event_id="event-page1")],
            "nextPageToken": "page2-token",
        }
        page_2 = {
            "items": [_make_google_event(event_id="event-page2")],
            "nextSyncToken": "final-sync-token",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(side_effect=[page_1, page_2])

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        # list_events should have been called twice (two pages)
        assert mock_client.list_events.call_count == 2
        # Two outbox events should be added (one per page)
        assert mock_session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_sync_skips_cancellation_for_past_events(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Cancelled events whose end date is in the past should be skipped, not cancelled.

        Some calendars (e.g. shared/subscribed) don't preserve past events and
        return them as cancelled during incremental sync. Since the event already
        happened, we should not mark the journal as cancelled.
        """
        from datetime import UTC, datetime, timedelta

        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]

        token_result = MagicMock()
        token_result.fetchone.return_value = None

        # Existing link for the cancelled event
        existing_link = MagicMock()
        existing_link.external_version = '"etag-old"'
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 42
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        # Journal end date query — event ended 3 days ago (well past the 1-day buffer)
        past_end_date = datetime.now(UTC) - timedelta(days=3)
        journal_end_result = MagicMock()
        journal_end_result.scalar.return_value = past_end_date

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            journal_end_result,  # journal end date lookup
            MagicMock(),  # sync token save
        ]

        # Google returns a cancelled event (minimal — only id + status as per API spec)
        cancelled_event = {
            "id": "google-event-past",
            "status": "cancelled",
            "etag": '"etag-cancelled"',
        }
        google_events = {
            "items": [cancelled_event],
            "nextSyncToken": "new-sync-token",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        # No outbox event should be created — the cancellation was skipped
        mock_session.add.assert_not_called()
        assert result["events_skipped"] >= 1

    @pytest.mark.asyncio
    async def test_sync_cancels_future_events_normally(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Cancelled events whose end date is in the future should still be cancelled."""
        from datetime import UTC, datetime, timedelta

        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]

        token_result = MagicMock()
        token_result.fetchone.return_value = None

        # Existing link for the cancelled event
        existing_link = MagicMock()
        existing_link.external_version = '"etag-old"'
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 99
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        # Journal end date query — event ends tomorrow (in the future)
        future_end_date = datetime.now(UTC) + timedelta(days=1)
        journal_end_result = MagicMock()
        journal_end_result.scalar.return_value = future_end_date

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            journal_end_result,  # journal end date lookup
            MagicMock(),  # sync token save
        ]

        cancelled_event = {
            "id": "google-event-future",
            "status": "cancelled",
            "etag": '"etag-cancelled"',
        }
        google_events = {
            "items": [cancelled_event],
            "nextSyncToken": "new-sync-token",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        # Outbox event SHOULD be created — this is a genuine cancellation
        mock_session.add.assert_called_once()
        assert result.get("events_cancelled", 0) >= 1

    @pytest.mark.asyncio
    async def test_sync_does_not_skip_same_day_all_day_cancellation(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Same-day all-day events with midnight-normalised end dates must not be skipped.

        The 1-day buffer ensures that events ending at midnight today (all-day events
        stored as 00:00:00 UTC) are still eligible for genuine cancellation.
        """
        from datetime import UTC, datetime

        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]

        token_result = MagicMock()
        token_result.fetchone.return_value = None

        existing_link = MagicMock()
        existing_link.external_version = '"etag-old"'
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 101
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        # End date is midnight today (how all-day events are stored)
        today_midnight = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        journal_end_result = MagicMock()
        journal_end_result.scalar.return_value = today_midnight

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            journal_end_result,  # journal end date lookup
            MagicMock(),  # sync token save
        ]

        cancelled_event = {
            "id": "google-event-same-day",
            "status": "cancelled",
            "etag": '"etag-cancelled"',
        }
        google_events = {
            "items": [cancelled_event],
            "nextSyncToken": "new-sync-token",
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch(
            "worker._create_google_client",
            return_value=mock_client,
        ):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        # Outbox event SHOULD be created — same-day events must not be skipped
        mock_session.add.assert_called_once()
        assert result.get("events_cancelled", 0) >= 1

    @pytest.mark.asyncio
    async def test_sync_invalid_sync_token_clears_token(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """When the API returns 410 Gone for a sync token, it should clear the token and retry."""
        from googleapiclient.errors import HttpError

        from worker import sync_calendar_events

        synced_cal = _make_calendar_row(is_synced_to_google=True)
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [synced_cal]

        # Setup existing sync token
        token_result = MagicMock()
        mock_row = MagicMock()
        mock_row.sync_token = "invalid-token"
        from datetime import UTC, datetime

        mock_row.created_at = datetime.now(UTC)
        token_result.fetchone.return_value = mock_row

        mock_session.execute.side_effect = [
            cal_result,  # calendars
            token_result,  # token
            MagicMock(),  # delete token
            MagicMock(),  # save new token
        ]

        mock_client = MagicMock()

        # Create mock HttpError
        mock_resp = MagicMock()
        mock_resp.status = 410
        http_error = HttpError(resp=mock_resp, content=b"Sync token is no longer valid")

        # First call raises HttpError, second call succeeds
        google_events = {
            "items": [],
            "nextSyncToken": "new-sync-token",
        }
        mock_client.list_events = AsyncMock(side_effect=[http_error, google_events])

        with patch("worker._create_google_client", return_value=mock_client):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "incremental"
            )

        assert result["status"] == "success"

        # Verify the client was called twice
        assert mock_client.list_events.call_count == 2

        # First call should have the sync_token
        first_call_args = mock_client.list_events.call_args_list[0][1]
        assert first_call_args["sync_token"] == "invalid-token"
        assert first_call_args["single_events"] is True

        # Second call should not have sync_token, but should have time_min and time_max
        second_call_args = mock_client.list_events.call_args_list[1][1]
        assert "sync_token" not in second_call_args
        assert "time_min" in second_call_args
        assert "time_max" in second_call_args
        assert second_call_args["single_events"] is True
