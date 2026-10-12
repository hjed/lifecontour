"""A Strava sync leaves an activity a journal merge absorbed alone.

A ``replace`` merge of two Strava journals drops the rival activity's links
and keeps it as a merged alias of the survivor. The backend refuses to
re-import it whatever the worker sends; checking here spares the webhook and
the batch sync from sending a create for it at all.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.repositories.merged_alias_repository import (
    ExternalRecord,
    MergedAliasRepository,
)
from sqlalchemy import text

from strava_models import StravaActivity
from strava_sync_service import StravaSyncService

USER_ID = "strava-merged-alias-user"
ABSORBED_ACTIVITY = 222


def _activity(activity_id: int) -> StravaActivity:
    return StravaActivity(
        id=activity_id,
        name="Morning Ride",
        type="Ride",
        sport_type="Ride",
        start_date="2026-03-15T08:00:00Z",
        elapsed_time=3600,
        moving_time=3400,
        distance=10000.0,
        total_elevation_gain=150.0,
    )


async def _seed_survivor_of_a_merge(db_session: Any) -> None:
    now = datetime.now(UTC)
    result = await db_session.execute(
        text("""
            INSERT INTO journals (user_id, title, content,
                event_date_range_start, event_date_range_end)
            VALUES (:user_id, 'Morning Ride', '', :now, :now)
            RETURNING id
        """),
        {"user_id": USER_ID, "now": now},
    )
    await MergedAliasRepository(db_session).record_aliases(
        journal_id=int(result.scalar_one()),
        user_id=USER_ID,
        records=[
            ExternalRecord(
                integration_source="strava", external_id=str(ABSORBED_ACTIVITY)
            )
        ],
    )


def _service(activity_id: int) -> StravaSyncService:
    client = AsyncMock()
    client.get_activity = AsyncMock(return_value=_activity(activity_id))
    client.get_activity_streams = AsyncMock(return_value=None)
    return StravaSyncService(api_client=client, user_id=USER_ID)


@pytest.mark.asyncio
class TestMergedAliasStravaSync:
    async def test_a_webhook_for_an_absorbed_activity_sends_nothing(
        self, db_session: Any
    ) -> None:
        await _seed_survivor_of_a_merge(db_session)

        events = await _service(ABSORBED_ACTIVITY).sync_single_activity(
            ABSORBED_ACTIVITY, db_session
        )

        assert events == []

    async def test_a_batch_sync_skips_an_absorbed_activity(
        self, db_session: Any
    ) -> None:
        await _seed_survivor_of_a_merge(db_session)

        @asynccontextmanager
        async def session_factory():  # type: ignore[no-untyped-def]
            yield db_session

        result = await _service(ABSORBED_ACTIVITY).sync_activity_batch(
            activity_ids=[ABSORBED_ACTIVITY], session_factory=session_factory
        )

        assert result == {"synced": 0, "skipped": 1, "failed": 0}

    async def test_an_unrelated_activity_is_still_sent(self, db_session: Any) -> None:
        await _seed_survivor_of_a_merge(db_session)

        events = await _service(333).sync_single_activity(333, db_session)

        assert [event.event_type for event in events] == ["journal_event.created"]
