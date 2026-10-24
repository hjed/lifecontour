"""A sync event is never applied to a calendar another user owns.

The processor creates an integration's calendar the first time an event names
it, owned by that event's user. A calendar id shared by every user was
therefore owned by whoever synced first, and everyone else's journals were
linked on a calendar they could not see (#1856). An event naming a calendar
someone else owns is refused rather than linked there.
"""

import pytest
from core_shared.integration_constants import SyntheticCalendar, synthetic_calendar_id
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    EVENT_TYPE_JOURNAL_EVENT_CREATED,
    JournalOutboxEventProcessingError,
)
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
