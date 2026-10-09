"""
Unit tests for StravaSyncService.

Tests sync orchestration logic, outbox event construction, deduplication,
and delete handling. All dependencies (API client, DB session) are mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strava_data_transformer import TransformedActivity
from strava_models import StravaActivity, StravaStreamSet
from strava_sync_service import StravaSyncService


def _make_activity(
    activity_id: int = 12345,
    name: str = "Morning Run",
    activity_type: str = "Run",
    start_latlng: list[float] | None = None,
    **overrides: Any,
) -> StravaActivity:
    """Build a minimal StravaActivity for testing."""
    return StravaActivity(
        id=activity_id,
        name=name,
        type=activity_type,
        sport_type=activity_type,
        start_date="2026-03-15T08:00:00Z",
        elapsed_time=3600,
        moving_time=3400,
        distance=10000.0,
        total_elevation_gain=150.0,
        start_latlng=start_latlng,
        **overrides,
    )


def _make_transformed(
    strava_activity_id: str = "12345",
    title: str = "Morning Run",
) -> TransformedActivity:
    """Build a minimal TransformedActivity for testing."""
    from core_shared.models.journals import EventDateRange, JournalType

    return TransformedActivity(
        title=title,
        content=None,
        event_date_range=EventDateRange(
            start=datetime(2026, 3, 15, 8, 0, tzinfo=UTC),
            end=datetime(2026, 3, 15, 9, 0, tzinfo=UTC),
        ),
        journal_types=[JournalType.JOGGING, JournalType.FITNESS],
        fitness_data_distance=10000,
        fitness_data_elevation_gain=150,
        fitness_data_duration=3400,
        fitness_data_calories=None,
        fitness_data_heart_rate_avg=None,
        fitness_data_heart_rate_max=None,
        fitness_data_strava_activity_id=strava_activity_id,
        elevation_loss=None,
        gpx_xml=None,
        version_hash="0" * 64,
        strava_athletes=[{"id": "user123", "name": "Test User"}],
    )


@pytest.fixture()
def mock_api_client() -> AsyncMock:
    """Mocked StravaAPIClient."""
    client = AsyncMock()
    client.get_activity = AsyncMock()
    client.list_activities = AsyncMock()
    client.get_activity_streams = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture()
def mock_session() -> MagicMock:
    """Mocked async database session with begin() async context manager."""
    session = MagicMock()
    session.add = MagicMock()
    session.execute = AsyncMock()

    # Support `async with session.begin():`
    class AsyncBeginContextManager:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session.begin = MagicMock(return_value=AsyncBeginContextManager())
    return session


@pytest.fixture()
def mock_session_factory(mock_session: MagicMock) -> MagicMock:
    """Mocked async database session factory.

    Returns the same mock_session from each call so test assertions
    (e.g. ``mock_session.add.call_count``) work as expected.
    """
    factory = MagicMock()

    # async with session_factory() returns an async context manager that yields mock_session
    class AsyncContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    factory.side_effect = lambda: AsyncContextManager()
    return factory


@pytest.fixture()
def sync_service(mock_api_client: AsyncMock) -> StravaSyncService:
    """StravaSyncService with mocked dependencies."""
    return StravaSyncService(
        api_client=mock_api_client,
        user_id="user-123",
    )


class TestSyncSingleActivity:
    """Tests for syncing a single Strava activity (webhook-triggered)."""

    @pytest.mark.asyncio()
    async def test_creates_outbox_event(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Fetches activity by ID, transforms, and creates outbox event."""
        activity = _make_activity()
        mock_api_client.get_activity.return_value = activity

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        mock_api_client.get_activity.assert_awaited_once_with(12345)
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "journal_event.created"

    @pytest.mark.asyncio()
    async def test_fetches_streams_when_gps_available(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Fetches activity streams when start_latlng is present."""
        activity = _make_activity(start_latlng=[-33.8, 151.2])
        mock_api_client.get_activity.return_value = activity
        mock_api_client.get_activity_streams.return_value = StravaStreamSet()

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        mock_api_client.get_activity_streams.assert_awaited_once_with(12345)

    @pytest.mark.asyncio()
    async def test_skips_streams_when_no_gps(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Does not fetch streams when start_latlng is None."""
        activity = _make_activity(start_latlng=None)
        mock_api_client.get_activity.return_value = activity

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        mock_api_client.get_activity_streams.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_creates_update_event_for_already_imported_activity(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Creates a journal_event.updated event when activity is already imported."""
        activity = _make_activity()
        mock_api_client.get_activity.return_value = activity

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=42,
        ):
            events = await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "journal_event.updated"
        assert event.event_data["existing_journal_id"] == 42


class TestListActivityBatches:
    """Tests for list_activity_batches async generator."""

    @pytest.mark.asyncio()
    async def test_yields_pages_until_empty(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Yields activity ID batches for each page, stops on empty page."""
        page1 = [_make_activity(activity_id=1), _make_activity(activity_id=2)]
        page2 = [_make_activity(activity_id=3)]
        page3: list[StravaActivity] = []

        mock_api_client.list_activities.side_effect = [page1, page2, page3]

        batches = []
        async for batch in sync_service.list_activity_batches():
            batches.append(batch)

        assert mock_api_client.list_activities.await_count == 3
        assert len(batches) == 2
        assert batches[0] == [1, 2]
        assert batches[1] == [3]

    @pytest.mark.asyncio()
    async def test_passes_after_timestamp(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Passes 'after' parameter for incremental sync."""
        mock_api_client.list_activities.return_value = []

        after_ts = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
        async for _ in sync_service.list_activity_batches(after_timestamp=after_ts):
            pass  # pragma: no cover

        call_kwargs = mock_api_client.list_activities.call_args
        assert (
            call_kwargs.kwargs.get("after") == after_ts
            or call_kwargs[1].get("after") == after_ts
        )

    @pytest.mark.asyncio()
    async def test_yields_nothing_when_no_activities(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Yields nothing when first page is empty."""
        mock_api_client.list_activities.return_value = []

        batches = []
        async for batch in sync_service.list_activity_batches():
            batches.append(batch)

        assert batches == []


class TestSyncActivityBatch:
    """Tests for sync_activity_batch (per-batch processing)."""

    @pytest.mark.asyncio()
    async def test_creates_outbox_event_for_each_activity(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Creates one outbox event per activity in the batch."""
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1),
            _make_activity(activity_id=2),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1, 2], session_factory=mock_session_factory
            )

        assert result["synced"] == 2
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert mock_session.add.call_count == 2

    @pytest.mark.asyncio()
    async def test_skips_already_imported_activities(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Skips activities that already have a journal entry and valid hash."""
        # Only the second activity will be fetched from API
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=2),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                side_effect=[42, None],  # first exists, second is new
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                side_effect=["abc123", None],  # first has hash, second is new
            ),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1, 2], session_factory=mock_session_factory
            )

        assert result["synced"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio()
    async def test_resyncs_stale_activity_with_invalidated_hash(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Re-syncs an existing activity whose version hash was invalidated."""
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1),
            _make_activity(activity_id=2),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                side_effect=[42, None],  # first exists, second is new
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                side_effect=[None, None],  # hash invalidated by migration
            ),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1, 2], session_factory=mock_session_factory
            )

        assert result["synced"] == 2
        assert result["skipped"] == 0

        # First event should be an update for the stale activity
        first_event = mock_session.add.call_args_list[0][0][0]
        assert first_event.event_type == "journal_event.updated"
        assert first_event.event_data["existing_journal_id"] == 42

        # Second event should be a create for the new activity
        second_event = mock_session.add.call_args_list[1][0][0]
        assert second_event.event_type == "journal_event.created"

    @pytest.mark.asyncio()
    async def test_continues_after_stream_fetch_failure(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Continues processing remaining activities when one stream fetch fails.

        Transient errors (TimeoutError) are retried up to 3 times before
        counting as failed.
        """
        # Activity 2 fails all 3 retry attempts; get_activity is called
        # once per attempt, so we need 3 copies for activity 2.
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=2, start_latlng=[-33.9, 151.3]),
            _make_activity(activity_id=2, start_latlng=[-33.9, 151.3]),
            _make_activity(activity_id=2, start_latlng=[-33.9, 151.3]),
            _make_activity(activity_id=3, start_latlng=[-34.0, 151.4]),
        ]

        # Activity 2's stream fetch always times out (3 retries)
        mock_api_client.get_activity_streams.side_effect = [
            StravaStreamSet(),
            TimeoutError("Connection timed out"),
            TimeoutError("Connection timed out"),
            TimeoutError("Connection timed out"),
            StravaStreamSet(),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("strava_sync_service.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1, 2, 3], session_factory=mock_session_factory
            )

        assert result["synced"] == 2
        assert result["failed"] == 1

    @pytest.mark.asyncio()
    async def test_continues_after_transform_failure(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Continues syncing when transformation raises a non-transient error.

        Non-transient errors (ValueError) fail immediately without retry.
        """
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1),
            _make_activity(activity_id=2),
            _make_activity(activity_id=3),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service._transformer,
                "transform",
                side_effect=[
                    _make_transformed(strava_activity_id="1"),
                    ValueError("Unexpected transform error"),
                    _make_transformed(strava_activity_id="3"),
                ],
            ),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1, 2, 3], session_factory=mock_session_factory
            )

        assert result["synced"] == 2
        assert result["failed"] == 1

    @pytest.mark.asyncio()
    async def test_continues_after_api_error(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Continues syncing when a 5xx Strava API error exhausts retries."""
        from strava_api_client import StravaAPIError

        # Activity 1 fails all 3 retries with 500
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=2, start_latlng=[-33.9, 151.3]),
        ]

        mock_api_client.get_activity_streams.side_effect = [
            StravaAPIError("Server error", status_code=500),
            StravaAPIError("Server error", status_code=500),
            StravaAPIError("Server error", status_code=500),
            StravaStreamSet(),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("strava_sync_service.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1, 2], session_factory=mock_session_factory
            )

        assert result["synced"] == 1
        assert result["failed"] == 1

    @pytest.mark.asyncio()
    async def test_retries_transient_error_then_succeeds(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Transient error on first attempt succeeds on retry."""
        # First attempt times out, second attempt succeeds
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
        ]

        mock_api_client.get_activity_streams.side_effect = [
            TimeoutError("Connection timed out"),
            StravaStreamSet(),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("strava_sync_service.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1], session_factory=mock_session_factory
            )

        assert result["synced"] == 1
        assert result["failed"] == 0

    @pytest.mark.asyncio()
    async def test_non_transient_error_fails_immediately(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Non-transient errors (e.g. 404) are not retried."""
        from strava_api_client import StravaAPIError

        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
        ]

        mock_api_client.get_activity_streams.side_effect = StravaAPIError(
            "Not found", status_code=404
        )

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1], session_factory=mock_session_factory
            )

        assert result["failed"] == 1
        # Only called once — no retries for 404
        assert mock_api_client.get_activity.await_count == 1

    @pytest.mark.asyncio()
    async def test_reports_counts_correctly(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Result dict reports synced, skipped, and failed accurately."""
        # Activity 1 (GPS + timeout): retried 3 times
        mock_api_client.get_activity.side_effect = [
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=1, start_latlng=[-33.8, 151.2]),
            _make_activity(activity_id=2),
            _make_activity(activity_id=3),
        ]

        mock_api_client.get_activity_streams.side_effect = [
            TimeoutError("timeout"),
            TimeoutError("timeout"),
            TimeoutError("timeout"),
        ]

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                side_effect=[None, None, None, 42, None],  # retries, existing, new
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                side_effect=[None, None, None, "abc123", None],  # existing has hash
            ),
            patch("strava_sync_service.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await sync_service.sync_activity_batch(
                activity_ids=[1, 2, 3], session_factory=mock_session_factory
            )

        # Activity 1: fails (GPS + timeout × 3), Activity 2: skipped, Activity 3: synced
        assert result["synced"] == 1
        assert result["skipped"] == 1
        assert result["failed"] == 1

    @pytest.mark.asyncio()
    async def test_rate_limit_error_bubbles_up(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Rate limit errors propagate to ARQ for job-level retry."""
        from strava_rate_limiter import StravaRateLimitError

        mock_api_client.get_activity.side_effect = StravaRateLimitError(
            "Rate limited", retry_after=900.0
        )

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                sync_service,
                "_find_stored_version_hash",
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(StravaRateLimitError),
        ):
            await sync_service.sync_activity_batch(
                activity_ids=[1], session_factory=mock_session_factory
            )

    @pytest.mark.asyncio()
    async def test_db_error_bubbles_up(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """SQLAlchemy errors propagate to ARQ for job-level retry."""
        from sqlalchemy.exc import OperationalError

        mock_api_client.get_activity.return_value = _make_activity(activity_id=1)

        with (
            patch.object(
                sync_service,
                "_find_existing_journal_id",
                new_callable=AsyncMock,
                side_effect=OperationalError(
                    "connection lost", params=None, orig=Exception()
                ),
            ),
            pytest.raises(OperationalError),
        ):
            await sync_service.sync_activity_batch(
                activity_ids=[1], session_factory=mock_session_factory
            )


class TestDeleteHandling:
    """Tests for activity deletion via webhook."""

    @pytest.mark.asyncio()
    async def test_creates_cancel_event(
        self,
        sync_service: StravaSyncService,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Creates a journal_event.cancelled outbox event for deleted activity."""
        # Mock finding the existing journal
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(journal_id=42)
        mock_session.execute.return_value = mock_result

        event = await sync_service.handle_delete(
            activity_id=12345, session=mock_session
        )

        assert event is not None
        assert event.event_type == "journal_event.cancelled"

    @pytest.mark.asyncio()
    async def test_returns_none_when_activity_not_found(
        self,
        sync_service: StravaSyncService,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Returns None when the deleted activity is not found in the database."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        event = await sync_service.handle_delete(
            activity_id=99999, session=mock_session
        )

        assert event is None


class TestOutboxEventStructure:
    """Tests for outbox event payload structure."""

    @pytest.mark.asyncio()
    async def test_event_has_correct_structure(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Outbox event contains required fields for inbound processor."""
        activity = _make_activity()
        mock_api_client.get_activity.return_value = activity

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        event = events[0]
        event_data = event.event_data

        assert "journal_data" in event_data
        assert "integration_source" in event_data
        assert event_data["integration_source"] == "strava"
        assert "external_event_id" in event_data
        assert event_data["external_event_id"] == "strava:12345"
        assert "calendar_id" in event_data
        assert "calendar_info_data" in event_data
        assert "sync_timestamp" in event_data

    @pytest.mark.asyncio()
    async def test_event_includes_fitness_data(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Outbox event journal_data includes fitness_data fields."""
        activity = _make_activity(
            calories=500.0,
            average_heartrate=155.0,
            max_heartrate=180.0,
        )
        mock_api_client.get_activity.return_value = activity

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        journal_data = events[0].event_data["journal_data"]
        assert "fitness_data" in journal_data

        fitness = journal_data["fitness_data"]
        assert fitness["distance"] == 10000
        assert fitness["elevation_gain"] == 150
        assert fitness["duration"] == 3600
        assert fitness["calories"] == 500
        assert fitness["heart_rate_avg"] == 155
        assert fitness["heart_rate_max"] == 180
        assert fitness["strava_activity_id"] == "12345"

    @pytest.mark.asyncio()
    async def test_event_includes_journal_types(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Outbox event journal_data includes journal_types list."""
        activity = _make_activity(activity_type="Hike")
        mock_api_client.get_activity.return_value = activity

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        journal_data = events[0].event_data["journal_data"]
        assert "journal_types" in journal_data
        types = journal_data["journal_types"]
        assert "bushwalking" in types
        assert "outdoor_activity" in types
        assert "fitness" in types

    @pytest.mark.asyncio()
    async def test_event_includes_gpx_xml_when_available(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Outbox event includes gpx_xml when streams are available."""
        activity = _make_activity(start_latlng=[-33.8, 151.2])
        mock_api_client.get_activity.return_value = activity

        from strava_models import StravaActivityStream

        streams = StravaStreamSet(
            latlng=StravaActivityStream(
                type="latlng",
                data=[[-33.8, 151.2], [-33.81, 151.21]],
                series_type="distance",
                original_size=2,
                resolution="high",
            ),
            altitude=StravaActivityStream(
                type="altitude",
                data=[100.0, 120.0],
                series_type="distance",
                original_size=2,
                resolution="high",
            ),
            time=StravaActivityStream(
                type="time",
                data=[0, 60],
                series_type="distance",
                original_size=2,
                resolution="high",
            ),
        )
        mock_api_client.get_activity_streams.return_value = streams

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        journal_data = events[0].event_data["journal_data"]
        assert journal_data.get("gpx_xml") is not None
        assert "<gpx" in journal_data["gpx_xml"]

    @pytest.mark.asyncio()
    async def test_event_includes_version_hash(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """Outbox event journal_data includes version_hash for SyncMetadata."""
        activity = _make_activity()
        mock_api_client.get_activity.return_value = activity

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_single_activity(
                activity_id=12345, session=mock_session
            )

        journal_data = events[0].event_data["journal_data"]
        assert "version_hash" in journal_data
        assert isinstance(journal_data["version_hash"], str)
        assert len(journal_data["version_hash"]) == 64  # SHA-256 hex length


def _lookup_session(
    mock_session: MagicMock, *, sync_metadata: int | None, fitness: int | None
) -> MagicMock:
    """Answer the journal-lookup queries from the two link stores separately.

    ``sync_metadata`` is the canonical store and may hold several activities per
    journal; ``journal_fitness_data`` holds at most one and is the legacy
    fallback. Each argument is the journal id that store knows about, or None.
    """

    async def execute(query: Any, params: Any = None) -> MagicMock:
        result = MagicMock()
        query_text = str(query)
        if "sync_metadata" in query_text:
            journal_id = sync_metadata
        elif "journal_fitness_data" in query_text:
            journal_id = fitness
        else:
            journal_id = None
        result.fetchone.return_value = (
            MagicMock(journal_id=journal_id) if journal_id is not None else None
        )
        return result

    mock_session.execute = AsyncMock(side_effect=execute)
    return mock_session


class TestJournalLookupForImportedActivity:
    """Which store tells the worker an activity has already been imported.

    After an additive merge a journal carries several Strava activities, but
    ``journal_fitness_data`` only has room for one id. The lookups therefore key
    on ``sync_metadata`` — otherwise the merged-away activity looks unknown and
    the next sync re-imports it as a duplicate journal.
    """

    @pytest.mark.asyncio()
    async def test_resolves_an_activity_linked_only_via_sync_metadata(
        self,
        sync_service: StravaSyncService,
        mock_session: MagicMock,
    ) -> None:
        session = _lookup_session(mock_session, sync_metadata=42, fitness=None)

        journal_id = await sync_service._find_existing_journal_id("222", session)

        assert journal_id == 42

    @pytest.mark.asyncio()
    async def test_falls_back_to_the_fitness_column(
        self,
        sync_service: StravaSyncService,
        mock_session: MagicMock,
    ) -> None:
        """Activities imported before sync metadata existed still resolve."""
        session = _lookup_session(mock_session, sync_metadata=None, fitness=7)

        journal_id = await sync_service._find_existing_journal_id("111", session)

        assert journal_id == 7

    @pytest.mark.asyncio()
    async def test_returns_none_when_neither_store_knows_the_activity(
        self,
        sync_service: StravaSyncService,
        mock_session: MagicMock,
    ) -> None:
        session = _lookup_session(mock_session, sync_metadata=None, fitness=None)

        journal_id = await sync_service._find_existing_journal_id("999", session)

        assert journal_id is None

    @pytest.mark.asyncio()
    async def test_delete_cancels_the_journal_found_via_sync_metadata(
        self,
        sync_service: StravaSyncService,
        mock_session: MagicMock,
        mock_session_factory: MagicMock,
    ) -> None:
        """A merged-away activity deleted on Strava still cancels its journal."""
        session = _lookup_session(mock_session, sync_metadata=42, fitness=None)

        event = await sync_service.handle_delete(activity_id=222, session=session)

        assert event is not None
        assert event.event_type == "journal_event.cancelled"
        assert event.event_data["existing_journal_id"] == 42


def _recording_session(mock_session: MagicMock) -> list[tuple[str, dict[str, Any]]]:
    """Record every statement and its parameters; every lookup finds nothing."""
    calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(query: Any, params: Any = None) -> MagicMock:
        calls.append((str(query), dict(params or {})))
        result = MagicMock()
        result.fetchone.return_value = None
        return result

    mock_session.execute = AsyncMock(side_effect=execute)
    return calls


class TestLookupsAreTheSyncingUsers:
    """An activity id is matched only against the syncing user's links and
    journals, never another user's."""

    @pytest.mark.asyncio()
    async def test_journal_lookup_is_keyed_by_the_owner(
        self, sync_service: StravaSyncService, mock_session: MagicMock
    ) -> None:
        calls = _recording_session(mock_session)

        await sync_service._find_existing_journal_id("12345", mock_session)

        assert len(calls) == 2
        for query, params in calls:
            assert "user_id = :user_id" in query
            assert params["user_id"] == sync_service._user_id

    @pytest.mark.asyncio()
    async def test_version_hash_lookup_is_keyed_by_the_owner(
        self, sync_service: StravaSyncService, mock_session: MagicMock
    ) -> None:
        calls = _recording_session(mock_session)

        await sync_service._find_stored_version_hash("12345", mock_session)

        [(query, params)] = calls
        assert "user_id = :user_id" in query
        assert params["user_id"] == sync_service._user_id
