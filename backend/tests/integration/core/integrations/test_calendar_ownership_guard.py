"""A sync event is never applied to a calendar another user owns.

The processor creates an integration's calendar the first time an event names
it, owned by that event's user. A calendar id shared by every user was
therefore owned by whoever synced first, and everyone else's journals were
linked on a calendar they could not see (#1856). An event naming a calendar
someone else owns is refused rather than linked there.
"""

from uuid import uuid4

import pytest
from core_shared.integration_constants import (
    LEGACY_SHARED_STRAVA_CALENDAR_ID,
    SyntheticCalendar,
    synthetic_calendar_id,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.integrations.journal_outbox_event_processor import (
    EVENT_TYPE_JOURNAL_EVENT_CREATED,
    JournalOutboxEventProcessingError,
)
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import overlap
from tests.integration.core.integrations.journal_sync_seeding import (
    build_processor,
    create_calendar,
    sync_event,
)

OWNER = "calendar-owner"
INTRUDER = "someone-else"


async def _count(connection: AsyncConnection, sql: str) -> int:
    result = await connection.execute(text(sql))
    count: int = result.scalar_one()
    return count


@pytest.mark.asyncio
async def test_an_event_on_another_users_calendar_is_refused(
    async_connection: AsyncConnection, clean_database: None
) -> None:
    calendar_id = await create_calendar(async_connection, user_id=OWNER)
    event = sync_event(
        EVENT_TYPE_JOURNAL_EVENT_CREATED,
        calendar_id=calendar_id,
        external_event_id="evt-1",
        user_id=INTRUDER,
    )

    with pytest.raises(JournalOutboxEventProcessingError, match="another user"):
        await build_processor(async_connection).process_event(event)

    assert await _count(async_connection, "SELECT count(*) FROM journals") == 0
    assert (
        await _count(
            async_connection, "SELECT count(*) FROM journal_external_event_links"
        )
        == 0
    )
    # Nor is the owner's calendar classified on the intruder's say-so.
    assert (
        await _count(
            async_connection,
            "SELECT count(*) FROM calendars WHERE integration_source IS NOT NULL",
        )
        == 0
    )


@pytest.mark.asyncio
async def test_a_new_synthetic_calendar_belongs_to_the_events_user(
    async_connection: AsyncConnection, clean_database: None
) -> None:
    calendar_id = synthetic_calendar_id(SyntheticCalendar.STRAVA, OWNER)
    event = sync_event(
        EVENT_TYPE_JOURNAL_EVENT_CREATED,
        calendar_id=calendar_id,
        external_event_id="strava:42",
        user_id=OWNER,
        integration_source="strava",
    )

    await build_processor(async_connection).process_event(event)

    result = await async_connection.execute(
        text(
            "SELECT user_id, integration_source FROM calendars "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": calendar_id},
    )
    assert tuple(result.one()) == (OWNER, "strava")


@pytest.mark.asyncio
async def test_an_event_on_the_users_own_calendar_is_applied(
    async_connection: AsyncConnection, clean_database: None
) -> None:
    calendar_id = await create_calendar(async_connection, user_id=OWNER)
    event = sync_event(
        EVENT_TYPE_JOURNAL_EVENT_CREATED,
        calendar_id=calendar_id,
        external_event_id="evt-1",
        user_id=OWNER,
    )

    await build_processor(async_connection).process_event(event)

    assert await _count(async_connection, "SELECT count(*) FROM journals") == 1


@pytest.mark.asyncio
async def test_a_second_user_racing_a_calendars_first_sync_is_refused(
    async_engine: AsyncEngine,
) -> None:
    """Two users' first events naming one calendar, the second arriving mid-insert.

    The second's insert waits on the first's and then finds the row, which a
    read in the same statement cannot see: its snapshot predates the first's
    commit. That is when the guard matters most, since it is how one id shared
    by every user came to be owned by whoever synced first. Committed for real
    (two connections cannot share the savepoint fixture) and deleted afterwards.
    """
    owner, intruder = f"race-owner-{uuid4()}", f"race-intruder-{uuid4()}"
    calendar_id = str(uuid4())

    async def first_sync(connection: AsyncConnection) -> None:
        event = sync_event(
            EVENT_TYPE_JOURNAL_EVENT_CREATED,
            calendar_id=calendar_id,
            external_event_id="race-1",
            user_id=owner,
        )
        await build_processor(connection).process_event(event)

    async def racing_sync(connection: AsyncConnection) -> None:
        event = sync_event(
            EVENT_TYPE_JOURNAL_EVENT_CREATED,
            calendar_id=calendar_id,
            external_event_id="race-2",
            user_id=intruder,
        )
        with pytest.raises(JournalOutboxEventProcessingError, match="another user"):
            async with unit_of_work(connection):
                await build_processor(connection).process_event(event)

    try:
        await overlap(async_engine, first_sync, racing_sync)

        async with async_engine.connect() as check:
            owners = await check.execute(
                text("SELECT user_id FROM journals WHERE user_id = ANY(:users)"),
                {"users": [owner, intruder]},
            )
            assert [row.user_id for row in owners] == [owner]
    finally:
        async with async_engine.connect() as cleanup:
            journal_ids = [
                row.id
                for row in await cleanup.execute(
                    text("SELECT id FROM journals WHERE user_id = ANY(:users)"),
                    {"users": [owner, intruder]},
                )
            ]
            for statement in (
                "DELETE FROM outbox_events WHERE aggregate_id = ANY(:ids)",
                "DELETE FROM journals WHERE id = ANY(:ids)",
                "DELETE FROM calendars WHERE id = CAST(:calendar_id AS uuid)",
            ):
                await cleanup.execute(
                    text(statement), {"ids": journal_ids, "calendar_id": calendar_id}
                )
            await cleanup.commit()


async def test_an_in_flight_event_on_the_old_shared_strava_calendar_lands_on_the_users_own(
    async_connection: AsyncConnection, clean_database: None
) -> None:
    """Events sent before the worker moved to per-user calendars still arrive.

    They name the one calendar every user used to share; applied there, the
    first user's event would recreate it as theirs and every other user's would
    be refused.
    """
    for user_id, activity in ((OWNER, "1"), (INTRUDER, "2")):
        event = sync_event(
            EVENT_TYPE_JOURNAL_EVENT_CREATED,
            calendar_id=LEGACY_SHARED_STRAVA_CALENDAR_ID,
            external_event_id=f"strava:{activity}",
            user_id=user_id,
            integration_source="strava",
        )
        await build_processor(async_connection).process_event(event)

    result = await async_connection.execute(
        text(
            "SELECT j.user_id, CAST(l.calendar_id AS text) "
            "FROM journal_external_event_links l "
            "JOIN journals j ON j.id = l.journal_id ORDER BY j.user_id"
        )
    )
    assert [tuple(row) for row in result] == sorted(
        (user_id, synthetic_calendar_id(SyntheticCalendar.STRAVA, user_id))
        for user_id in (OWNER, INTRUDER)
    )
    assert (
        await _count(
            async_connection,
            "SELECT count(*) FROM calendars "
            f"WHERE id = CAST('{LEGACY_SHARED_STRAVA_CALENDAR_ID}' AS uuid)",
        )
        == 0
    )
