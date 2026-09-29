"""Seeding two journal series for the series-merge REST and MCP tests.

Rows are written directly: these tests are about what a merge does with the
series it is given, not about how the series came to exist.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# The owner the authenticated test client and the MCP session both act as.
USER_ID = "test-user-123"
OTHER_USER_ID = "series-merge-other-user"


async def seed_calendar(
    connection: AsyncConnection, name: str = "Work", *, user_id: str = USER_ID
) -> uuid.UUID:
    """A calendar row."""
    calendar_id = uuid.uuid4()
    await connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, :name, '#336699')
        """),
        {"id": calendar_id, "user_id": user_id, "name": name},
    )
    return calendar_id


async def seed_series(
    connection: AsyncConnection,
    name: str,
    *,
    user_id: str = USER_ID,
    calendar_id: uuid.UUID | None = None,
    recurring_event_id: str | None = None,
) -> uuid.UUID:
    """A series row; pass a recurrence key to make it look auto-created."""
    result = await connection.execute(
        text("""
            INSERT INTO journal_series
                (user_id, name, calendar_id, recurring_event_id)
            VALUES (:user_id, :name, :calendar_id, :recurring_event_id)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "name": name,
            "calendar_id": calendar_id,
            "recurring_event_id": recurring_event_id,
        },
    )
    series_id: uuid.UUID = result.scalar_one()
    return series_id


async def seed_member(
    connection: AsyncConnection,
    series_id: uuid.UUID,
    *,
    title: str,
    start: datetime,
    content: str = "",
    calendar_id: uuid.UUID | None = None,
    location: str | None = None,
    user_id: str = USER_ID,
) -> int:
    """A journal in ``series_id``; an event displayed in ``calendar_id`` if given."""
    result = await connection.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content,
                 event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "title": title,
            "content": content,
            "start": start,
            "end": start + timedelta(hours=1),
        },
    )
    journal_id = int(result.scalar_one())
    if calendar_id is not None:
        await connection.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, location)
                VALUES (:journal_id, :calendar_id, false, :location)
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "location": location,
            },
        )
    await add_to_series(connection, series_id, journal_id)
    return journal_id


async def add_to_series(
    connection: AsyncConnection, series_id: uuid.UUID, journal_id: int
) -> None:
    """Add an existing journal to a series."""
    await connection.execute(
        text("""
            INSERT INTO journal_series_members (series_id, journal_id)
            VALUES (:series_id, :journal_id)
        """),
        {"series_id": series_id, "journal_id": journal_id},
    )


async def member_ids(connection: AsyncConnection, series_id: uuid.UUID) -> set[int]:
    """The journals currently in a series."""
    result = await connection.execute(
        text("SELECT journal_id FROM journal_series_members WHERE series_id = :id"),
        {"id": series_id},
    )
    return {int(row.journal_id) for row in result}


async def series_exists(connection: AsyncConnection, series_id: uuid.UUID) -> bool:
    """Whether the series row is still there."""
    result = await connection.execute(
        text("SELECT 1 FROM journal_series WHERE id = :id"), {"id": series_id}
    )
    return result.scalar() is not None


async def journal_exists(connection: AsyncConnection, journal_id: int) -> bool:
    """Whether the journal row is still there."""
    result = await connection.execute(
        text("SELECT 1 FROM journals WHERE id = :id"), {"id": journal_id}
    )
    return result.scalar() is not None
