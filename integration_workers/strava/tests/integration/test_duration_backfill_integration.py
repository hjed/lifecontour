"""Integration tests for the elapsed-time duration backfill service.

Real PostgreSQL for the journal links and the outbox; the Strava API is a
stub, as only the listing's moving and elapsed times matter here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from duration_backfill import StravaDurationBackfillService
from strava_models import StravaActivity

USER_ID = "duration-backfill-user"
OTHER_USER_ID = "someone-else"
NOW = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


def _activity(activity_id: int, *, moving: int, elapsed: int) -> StravaActivity:
    return StravaActivity(
        id=activity_id,
        name=f"Activity {activity_id}",
        type="Ride",
        sport_type="Ride",
        start_date="2026-05-10T02:00:00Z",
        elapsed_time=elapsed,
        moving_time=moving,
        distance=20000.0,
        total_elevation_gain=100.0,
    )


class _StubStravaClient:
    """Serves a fixed activity list in pages, recording the pages asked for."""

    def __init__(self, activities: list[StravaActivity]) -> None:
        self._activities = activities
        self.requests: list[tuple[int, int]] = []

    async def list_activities(
        self, *, page: int = 1, per_page: int = 30, **_: Any
    ) -> list[StravaActivity]:
        self.requests.append((page, per_page))
        start = (page - 1) * per_page
        return self._activities[start : start + per_page]


async def _seed_journal(
    session: AsyncSession, *, user_id: str = USER_ID, duration: int | None
) -> int:
    result = await session.execute(
        text("""
            INSERT INTO journals (user_id, title, content,
                event_date_range_start, event_date_range_end)
            VALUES (:user_id, 'Ride', '', :now, :now)
            RETURNING id
        """),
        {"user_id": user_id, "now": NOW},
    )
    journal_id: int = result.scalar_one()
    await session.execute(
        text("""
            INSERT INTO journal_fitness_data (journal_id, duration)
            VALUES (:journal_id, :duration)
        """),
        {"journal_id": journal_id, "duration": duration},
    )
    return journal_id


async def _link(
    session: AsyncSession, journal_id: int, activity_id: int, user_id: str = USER_ID
) -> None:
    await session.execute(
        text("""
            INSERT INTO sync_metadata
                (user_id, internal_id, internal_entity_type, integration_source,
                 external_id, version_hash, sync_status, last_synced_at,
                 created_at, updated_at)
            VALUES (:user_id, :journal_id, 'journal', 'strava', :external_id,
                    'hash', 'success', NOW(), NOW(), NOW())
        """),
        {"user_id": user_id, "journal_id": journal_id, "external_id": str(activity_id)},
    )


async def _correction_events(session: AsyncSession) -> dict[int, dict[str, Any]]:
    result = await session.execute(
        text("""
            SELECT aggregate_id, event_data FROM outbox_events
            WHERE event_type = 'journal_event.fitness_duration_corrected'
        """)
    )
    # Raw SQL hands JSONB back as text on this driver.
    return {row.aggregate_id: json.loads(row.event_data) for row in result}


def _session_factory(session: AsyncSession) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield session

    return factory


@pytest.mark.asyncio
async def test_emits_a_correction_per_linked_journal(db_session: AsyncSession) -> None:
    single = await _seed_journal(db_session, duration=3000)
    await _link(db_session, single, 111)
    merged = await _seed_journal(db_session, duration=4200)
    await _link(db_session, merged, 222)
    await _link(db_session, merged, 333)
    await db_session.flush()
    client = _StubStravaClient(
        [
            _activity(111, moving=3000, elapsed=3600),
            _activity(222, moving=1000, elapsed=1100),
            _activity(333, moving=3200, elapsed=3500),
        ]
    )

    result = await StravaDurationBackfillService(
        api_client=client,  # type: ignore[arg-type]
        user_id=USER_ID,
    ).run(_session_factory(db_session))

    assert result == {"journals": 2, "corrections": 2}
    events = await _correction_events(db_session)
    assert events[single]["expected_durations"] == [3000]
    assert events[single]["corrected_duration"] == 3600
    assert events[single]["user_id"] == USER_ID
    assert set(events[merged]["expected_durations"]) == {4200, 4300, 4500}
    assert events[merged]["corrected_duration"] == 4600
    assert sorted(events[merged]["strava_activity_ids"]) == ["222", "333"]


@pytest.mark.asyncio
async def test_another_users_links_are_not_corrected(db_session: AsyncSession) -> None:
    theirs = await _seed_journal(db_session, user_id=OTHER_USER_ID, duration=3000)
    await _link(db_session, theirs, 111, user_id=OTHER_USER_ID)
    await db_session.flush()
    client = _StubStravaClient([_activity(111, moving=3000, elapsed=3600)])

    result = await StravaDurationBackfillService(
        api_client=client,  # type: ignore[arg-type]
        user_id=USER_ID,
    ).run(_session_factory(db_session))

    assert result == {"journals": 0, "corrections": 0}
    assert await _correction_events(db_session) == {}


@pytest.mark.asyncio
async def test_a_journal_linked_only_by_its_fitness_activity_id_is_corrected(
    db_session: AsyncSession,
) -> None:
    """The sync's own dedup also matches journal_fitness_data.strava_activity_id."""
    journal_id = await _seed_journal(db_session, duration=3000)
    await db_session.execute(
        text(
            "UPDATE journal_fitness_data SET strava_activity_id = '111' "
            "WHERE journal_id = :journal_id"
        ),
        {"journal_id": journal_id},
    )
    await db_session.flush()
    client = _StubStravaClient([_activity(111, moving=3000, elapsed=3600)])

    await StravaDurationBackfillService(
        api_client=client,  # type: ignore[arg-type]
        user_id=USER_ID,
    ).run(_session_factory(db_session))

    events = await _correction_events(db_session)
    assert events[journal_id]["expected_durations"] == [3000]


@pytest.mark.asyncio
async def test_pages_through_every_activity(db_session: AsyncSession) -> None:
    activities = [
        _activity(1000 + n, moving=100, elapsed=150)
        for n in range(StravaDurationBackfillService.PAGE_SIZE + 1)
    ]
    journal_id = await _seed_journal(db_session, duration=100)
    await _link(db_session, journal_id, activities[-1].id)
    await db_session.flush()
    client = _StubStravaClient(activities)

    await StravaDurationBackfillService(
        api_client=client,  # type: ignore[arg-type]
        user_id=USER_ID,
    ).run(_session_factory(db_session))

    page_size = StravaDurationBackfillService.PAGE_SIZE
    assert client.requests == [(1, page_size), (2, page_size), (3, page_size)]
    assert journal_id in await _correction_events(db_session)
