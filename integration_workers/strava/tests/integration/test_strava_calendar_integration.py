"""The calendar a Strava event names, against the real ``calendars`` table.

Each user's activities are linked on their own calendar (#1856).
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.integration_constants import (
    SyntheticCalendar,
    synthetic_calendar_id,
)

from strava_models import StravaActivity
from strava_sync_service import StravaSyncService

USER_ID = "strava-calendar-user"
ACTIVITY_ID = 444


def _service() -> StravaSyncService:
    client = AsyncMock()
    client.get_activity = AsyncMock(
        return_value=StravaActivity(
            id=ACTIVITY_ID,
            name="Morning Ride",
            type="Ride",
            sport_type="Ride",
            start_date="2026-03-15T08:00:00Z",
            elapsed_time=3600,
            moving_time=3400,
            distance=10000.0,
            total_elevation_gain=150.0,
        )
    )
    client.get_activity_streams = AsyncMock(return_value=None)
    return StravaSyncService(api_client=client, user_id=USER_ID)


@pytest.mark.asyncio
class TestStravaCalendar:
    async def test_an_import_names_the_users_own_calendar(
        self, db_session: Any
    ) -> None:
        [event] = await _service().sync_single_activity(ACTIVITY_ID, db_session)

        own = synthetic_calendar_id(SyntheticCalendar.STRAVA, USER_ID)
        assert event.event_data["calendar_id"] == own
        assert event.event_data["calendar_info_data"]["calendar_id"] == own
