"""Unit tests for sync_calendar_events ARQ task."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.testing import make_arq_ctx, make_mock_redis

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
    recurring_event_id: str | None = None,
    ical_uid: str | None = None,
    original_start_dt: str | None = None,
) -> dict[str, Any]:
    """Build a raw Google Calendar event response dict."""
    event: dict[str, Any] = {
        "id": event_id,
        "summary": summary,
        "description": description,
        "etag": etag,
        "status": status,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
    }
    if recurring_event_id is not None:
        event["recurringEventId"] = recurring_event_id
    if ical_uid is not None:
        event["iCalUID"] = ical_uid
    if original_start_dt is not None:
        event["originalStartTime"] = {"dateTime": original_start_dt}
    return event


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
        return make_arq_ctx(
            session_factory=mock_session_factory, redis=make_mock_redis()
        )

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = None  # No sync token

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = None

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
        token_result.scalar.return_value = "invalid-token"

        mock_session.execute.side_effect = [
            cal_result,  # calendars
            token_result,  # token
            MagicMock(),  # update token
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

        # Second call should not have sync_token, but should have time_min
        second_call_args = mock_client.list_events.call_args_list[1][1]
        assert "sync_token" not in second_call_args
        assert "time_min" in second_call_args
        assert second_call_args["single_events"] is True


class TestSyncRecurringSeries:
    """Recurring-series support: recurring id passthrough, master
    cancellations, and backfill promotion of unchanged events."""

    @pytest.fixture(autouse=True)
    def mock_metrics_collector(self):
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
        return make_arq_ctx(
            session_factory=mock_session_factory, redis=make_mock_redis()
        )

    @staticmethod
    async def _run_sync_with_events(
        mock_ctx: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run sync_calendar_events with the given raw Google items."""
        from worker import sync_calendar_events

        google_events = {"items": items, "nextSyncToken": "new-sync-token"}
        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch("worker._create_google_client", return_value=mock_client):
            return await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

    @pytest.mark.asyncio
    async def test_created_outbox_event_includes_recurring_event_id(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """New recurring instances carry the master id into the outbox payload."""
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None
        link_result = MagicMock()
        link_result.fetchone.return_value = None

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            MagicMock(),  # sync token save
        ]

        result = await self._run_sync_with_events(
            mock_ctx,
            [
                _make_google_event(
                    event_id="master-1_20260320T100000Z",
                    recurring_event_id="master-1",
                )
            ],
        )

        assert result["status"] == "success"
        mock_session.add.assert_called_once()
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_type == "journal_event.created"
        assert outbox_event.event_data["recurring_event_id"] == "master-1"

    @pytest.mark.asyncio
    async def test_cancelled_instance_outbox_event_includes_recurring_event_id(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Cancelled recurring instances carry the master id for deletion logic."""
        from datetime import UTC, datetime, timedelta

        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None

        existing_link = MagicMock()
        existing_link.external_version = '"etag-old"'
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 42
        existing_link.recurring_event_id = None
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        journal_end_result = MagicMock()
        journal_end_result.scalar.return_value = datetime.now(UTC) + timedelta(days=7)

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            journal_end_result,  # journal end date lookup
            MagicMock(),  # sync token save
        ]

        result = await self._run_sync_with_events(
            mock_ctx,
            [
                {
                    "id": "master-1_20260320T100000Z",
                    "status": "cancelled",
                    "etag": '"etag-cancelled"',
                    "recurringEventId": "master-1",
                }
            ],
        )

        assert result["status"] == "success"
        mock_session.add.assert_called_once()
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_type == "journal_event.cancelled"
        assert outbox_event.event_data["recurring_event_id"] == "master-1"

    @pytest.mark.asyncio
    async def test_master_cancellation_emits_series_cancelled_event(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """A cancelled master id with linked instances emits one series event."""
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None

        # No direct link for the master id itself…
        link_result = MagicMock()
        link_result.fetchone.return_value = None
        # …but instances of the series are linked (EXISTS finds a row).
        series_links_result = MagicMock()
        series_links_result.scalar.return_value = 1

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            series_links_result,  # series links EXISTS check
            MagicMock(),  # sync token save
        ]

        result = await self._run_sync_with_events(
            mock_ctx,
            [
                {
                    "id": "master-1",
                    "status": "cancelled",
                    "etag": '"etag-cancelled"',
                }
            ],
        )

        assert result["status"] == "success"
        mock_session.add.assert_called_once()
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_type == "journal_event.series_cancelled"
        assert outbox_event.event_data["recurring_event_id"] == "master-1"
        assert outbox_event.event_data["calendar_id"] == str(TEST_CALENDAR_UUID)

    @pytest.mark.asyncio
    async def test_master_cancellation_without_series_links_is_skipped(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """A cancelled unknown id with no linked instances stays skipped."""
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None
        link_result = MagicMock()
        link_result.fetchone.return_value = None
        series_links_result = MagicMock()
        series_links_result.scalar.return_value = None

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            series_links_result,  # series links EXISTS check
            MagicMock(),  # sync token save
        ]

        result = await self._run_sync_with_events(
            mock_ctx,
            [
                {
                    "id": "unknown-event",
                    "status": "cancelled",
                    "etag": '"etag-cancelled"',
                }
            ],
        )

        assert result["status"] == "success"
        mock_session.add.assert_not_called()
        assert result["events_skipped"] >= 1

    @pytest.mark.asyncio
    async def test_unchanged_event_with_new_recurring_id_promoted_to_update(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """ETag-unchanged events backfill the recurring id via an UPDATE."""
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None

        existing_link = MagicMock()
        existing_link.external_version = '"etag-abc"'  # same as the event
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 42
        existing_link.recurring_event_id = None  # not yet backfilled
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            MagicMock(),  # sync token save
        ]

        result = await self._run_sync_with_events(
            mock_ctx,
            [
                _make_google_event(
                    event_id="master-1_20260320T100000Z",
                    etag='"etag-abc"',
                    recurring_event_id="master-1",
                )
            ],
        )

        assert result["status"] == "success"
        mock_session.add.assert_called_once()
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_type == "journal_event.updated"
        assert outbox_event.event_data["recurring_event_id"] == "master-1"
        assert outbox_event.event_data["existing_journal_id"] == 42

    @pytest.mark.asyncio
    async def test_unchanged_event_with_stored_recurring_id_stays_skipped(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Already-backfilled unchanged events are not re-synced."""
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None

        existing_link = MagicMock()
        existing_link.external_version = '"etag-abc"'  # same as the event
        existing_link.sync_capability = "bidirectional"
        existing_link.journal_id = 42
        existing_link.recurring_event_id = "master-1"  # already backfilled
        link_result = MagicMock()
        link_result.fetchone.return_value = existing_link

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            MagicMock(),  # sync token save
        ]

        result = await self._run_sync_with_events(
            mock_ctx,
            [
                _make_google_event(
                    event_id="master-1_20260320T100000Z",
                    etag='"etag-abc"',
                    recurring_event_id="master-1",
                )
            ],
        )

        assert result["status"] == "success"
        mock_session.add.assert_not_called()
        assert result["events_skipped"] >= 1


class TestMasterCancellationLegacyLinks:
    """Audit fix: legacy links (no backfilled recurring id) must still gate
    CANCEL_SERIES via an external_event_id prefix fallback."""

    @pytest.fixture(autouse=True)
    def mock_metrics_collector(self):
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
        return make_arq_ctx(
            session_factory=mock_session_factory, redis=make_mock_redis()
        )

    @pytest.mark.asyncio
    async def test_series_links_check_includes_prefix_fallback(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """The EXISTS gate matches unbackfilled links by instance-id prefix so
        deleting a legacy series still emits journal_event.series_cancelled."""
        from worker import sync_calendar_events

        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None
        link_result = MagicMock()
        link_result.fetchone.return_value = None
        series_links_result = MagicMock()
        series_links_result.scalar.return_value = 1

        mock_session.execute.side_effect = [
            cal_result,  # calendar query
            token_result,  # sync token query
            link_result,  # existing link lookup
            series_links_result,  # series links EXISTS check
            MagicMock(),  # sync token save
        ]

        google_events = {
            "items": [{"id": "master-1", "status": "cancelled", "etag": '"etag-c"'}],
            "nextSyncToken": "new-sync-token",
        }
        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=google_events)

        with patch("worker._create_google_client", return_value=mock_client):
            result = await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

        assert result["status"] == "success"
        series_check_call = mock_session.execute.call_args_list[3]
        sql_text = str(series_check_call[0][0].text)
        assert "recurring_event_id = :recurring_event_id" in sql_text
        assert "recurring_event_id IS NULL" in sql_text
        assert "LIKE :instance_prefix" in sql_text
        assert series_check_call[0][1]["instance_prefix"] == "master-1\\_%"


class TestCrossCalendarDeDupe:
    """The same event in two calendars must become one journal.

    Google gives each calendar's copy its own event id, so the per-calendar
    link lookup can never see the other copy. The identity token is what
    joins them up.
    """

    @pytest.fixture(autouse=True)
    def mock_metrics_collector(self):
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
    def mock_ctx(self, mock_session: AsyncMock) -> dict[str, Any]:
        factory = MagicMock()
        factory.return_value = mock_session
        return make_arq_ctx(session_factory=factory, redis=make_mock_redis())

    @staticmethod
    async def _run_sync(
        mock_ctx: dict[str, Any], items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        from worker import sync_calendar_events

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(
            return_value={"items": items, "nextSyncToken": "new-sync-token"}
        )
        with patch("worker._create_google_client", return_value=mock_client):
            return await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

    @staticmethod
    def _queue(mock_session: AsyncMock, *results: Any) -> None:
        """Queue the ordered execute() results for one calendar's sync."""
        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None
        mock_session.execute.side_effect = [
            cal_result,  # synced calendars
            token_result,  # sync token
            *results,
            MagicMock(),  # sync token save
        ]

    @staticmethod
    def _no_link() -> MagicMock:
        result = MagicMock()
        result.fetchone.return_value = None
        return result

    @staticmethod
    def _identity_match(journal_id: int) -> MagicMock:
        row = MagicMock()
        row.journal_id = journal_id
        result = MagicMock()
        result.fetchone.return_value = row
        return result

    @pytest.mark.asyncio
    async def test_new_event_carries_its_identity_token(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """A created event tells the backend how to recognise its twin."""
        self._queue(mock_session, self._no_link(), self._no_link())

        result = await self._run_sync(
            mock_ctx,
            [_make_google_event(ical_uid="shared-uid@google.com")],
        )

        assert result["status"] == "success"
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_type == "journal_event.created"
        assert outbox_event.event_data["external_identity"] == (
            "google:shared-uid@google.com:"
        )

    @pytest.mark.asyncio
    async def test_recurring_instance_token_includes_its_start(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Instances share a uid, so the token has to separate them."""
        self._queue(mock_session, self._no_link(), self._no_link())

        result = await self._run_sync(
            mock_ctx,
            [
                _make_google_event(
                    event_id="master-1_20260320T100000Z",
                    recurring_event_id="master-1",
                    ical_uid="series-uid@google.com",
                    original_start_dt="2026-03-20T10:00:00Z",
                )
            ],
        )

        assert result["status"] == "success"
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_data["external_identity"] == (
            "google:series-uid@google.com:2026-03-20T10:00:00+00:00"
        )

    @pytest.mark.asyncio
    async def test_event_without_a_uid_carries_no_token(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """No trustworthy identity means the old per-calendar path, not a guess."""
        self._queue(mock_session, self._no_link())

        result = await self._run_sync(mock_ctx, [_make_google_event()])

        assert result["status"] == "success"
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_data["external_identity"] is None

    @pytest.mark.asyncio
    async def test_a_uidless_event_is_not_looked_up_by_identity(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """Without a token there is nothing to match on, so we don't ask."""
        self._queue(mock_session, self._no_link())

        await self._run_sync(mock_ctx, [_make_google_event()])

        queries = [str(call[0][0].text) for call in mock_session.execute.call_args_list]
        assert not any(
            "external_identity = :external_identity" in query for query in queries
        )

    @pytest.mark.asyncio
    async def test_second_calendars_copy_updates_the_existing_journal(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """The whole point: one journal, not two.

        The personal calendar's copy has its own event id, so the
        per-calendar lookup misses. The token finds the journal the work
        calendar already created, and the event becomes an update against
        it — which is what makes the backend add a second link rather than
        a second journal.
        """
        self._queue(mock_session, self._no_link(), self._identity_match(42))

        result = await self._run_sync(
            mock_ctx,
            [
                _make_google_event(
                    event_id="personal-copy-9",
                    ical_uid="shared-uid@google.com",
                )
            ],
        )

        assert result["status"] == "success"
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_type == "journal_event.updated"
        assert outbox_event.event_data["existing_journal_id"] == 42
        # The link it creates must belong to the calendar being synced, not
        # to the one that already holds a link.
        assert outbox_event.event_data["calendar_id"] == str(TEST_CALENDAR_UUID)
        assert outbox_event.event_data["external_event_id"] == "personal-copy-9"

    @pytest.mark.asyncio
    async def test_identity_lookup_is_scoped_to_the_user_and_other_calendars(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """A token is only meaningful within one user's own calendars."""
        self._queue(mock_session, self._no_link(), self._no_link())

        await self._run_sync(
            mock_ctx,
            [_make_google_event(ical_uid="shared-uid@google.com")],
        )

        identity_call = mock_session.execute.call_args_list[3]
        sql_text = str(identity_call[0][0].text)
        assert "external_identity = :external_identity" in sql_text
        assert "user_id = :user_id" in sql_text
        assert identity_call[0][1]["external_identity"] == (
            "google:shared-uid@google.com:"
        )
        assert identity_call[0][1]["user_id"] == "user-1"


class TestIdentityBackfill:
    """Links made before the token existed have to acquire one.

    Nothing else would ever give them one: an unchanged event is skipped on
    its ETag, so without a nudge the de-dupe would only ever work for events
    synced after the feature shipped.
    """

    @pytest.fixture(autouse=True)
    def mock_metrics_collector(self):
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
    def mock_ctx(self, mock_session: AsyncMock) -> dict[str, Any]:
        factory = MagicMock()
        factory.return_value = mock_session
        return make_arq_ctx(session_factory=factory, redis=make_mock_redis())

    @staticmethod
    def _existing_link(external_identity: str | None) -> MagicMock:
        link = MagicMock()
        link.external_version = '"etag-abc"'
        link.sync_capability = "bidirectional"
        link.journal_id = 42
        link.recurring_event_id = None
        link.external_identity = external_identity
        result = MagicMock()
        result.fetchone.return_value = link
        return result

    async def _run(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock, link: MagicMock
    ) -> dict[str, Any]:
        from worker import sync_calendar_events

        cal_result = MagicMock()
        cal_result.fetchall.return_value = [_make_calendar_row()]
        token_result = MagicMock()
        token_result.scalar.return_value = None
        mock_session.execute.side_effect = [
            cal_result,
            token_result,
            link,
            MagicMock(),  # sync token save
        ]

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(
            return_value={
                "items": [
                    _make_google_event(
                        etag='"etag-abc"',  # unchanged: normally skipped
                        ical_uid="shared-uid@google.com",
                    )
                ],
                "nextSyncToken": "new-sync-token",
            }
        )
        with patch("worker._create_google_client", return_value=mock_client):
            return await sync_calendar_events(
                mock_ctx, "test@example.com", "user-1", "full"
            )

    @pytest.mark.asyncio
    async def test_a_tokenless_link_is_resynced_once(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """An unchanged event is re-emitted so the token can be stored."""
        result = await self._run(mock_ctx, mock_session, self._existing_link(None))

        assert result["status"] == "success"
        mock_session.add.assert_called_once()
        outbox_event = mock_session.add.call_args[0][0]
        assert outbox_event.event_type == "journal_event.updated"
        assert outbox_event.event_data["existing_journal_id"] == 42
        assert outbox_event.event_data["external_identity"] == (
            "google:shared-uid@google.com:"
        )

    @pytest.mark.asyncio
    async def test_a_link_that_already_has_a_token_stays_skipped(
        self, mock_ctx: dict[str, Any], mock_session: AsyncMock
    ) -> None:
        """The backfill fires once, not on every sync forever."""
        result = await self._run(
            mock_ctx,
            mock_session,
            self._existing_link("google:shared-uid@google.com:"),
        )

        assert result["status"] == "success"
        mock_session.add.assert_not_called()
        assert result["events_skipped"] == 1
