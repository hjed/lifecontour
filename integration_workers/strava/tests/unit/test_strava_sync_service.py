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
    """Mocked async database session."""
    session = MagicMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    return session


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


class TestFullSync:
    """Tests for full historical activity sync."""

    @pytest.mark.asyncio()
    async def test_paginates_until_empty(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
    ) -> None:
        """Iterates pages until an empty response is returned."""
        page1 = [_make_activity(activity_id=1), _make_activity(activity_id=2)]
        page2 = [_make_activity(activity_id=3)]
        page3: list[StravaActivity] = []

        mock_api_client.list_activities.side_effect = [page1, page2, page3]

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_full(session=mock_session)

        assert mock_api_client.list_activities.await_count == 3
        assert len(events) == 3

    @pytest.mark.asyncio()
    async def test_creates_outbox_event_for_each_activity(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
    ) -> None:
        """Creates one outbox event per activity."""
        activities = [_make_activity(activity_id=i) for i in range(5)]
        mock_api_client.list_activities.side_effect = [activities, []]

        with patch.object(
            sync_service,
            "_find_existing_journal_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            events = await sync_service.sync_full(session=mock_session)

        assert len(events) == 5
        for event in events:
            assert event.event_type == "journal_event.created"

    @pytest.mark.asyncio()
    async def test_passes_after_timestamp(
        self,
        sync_service: StravaSyncService,
        mock_api_client: AsyncMock,
        mock_session: MagicMock,
    ) -> None:
        """Passes 'after' parameter for incremental sync."""
        mock_api_client.list_activities.return_value = []

        after_ts = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
        await sync_service.sync_full(session=mock_session, after_timestamp=after_ts)

        call_kwargs = mock_api_client.list_activities.call_args
        assert (
            call_kwargs.kwargs.get("after") == after_ts
            or call_kwargs[1].get("after") == after_ts
        )


class TestDeleteHandling:
    """Tests for activity deletion via webhook."""

    @pytest.mark.asyncio()
    async def test_creates_cancel_event(
        self, sync_service: StravaSyncService, mock_session: MagicMock
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
        self, sync_service: StravaSyncService, mock_session: MagicMock
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
        assert fitness["duration"] == 3400
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
