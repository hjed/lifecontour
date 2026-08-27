"""Seeding a journal that several calendars hold.

De-duplication gives one journal an ``journal_external_event_links`` row per
calendar holding the event, while ``journal_calendar_info`` still names the
single calendar it is *displayed* in. Arranging that takes three inserts and
the knowledge of which table means which, so the REST and MCP read tests
share it here rather than each carrying a copy.

The rows are written directly. These are read-model tests: how a journal
came to be linked to two calendars is the sync's business, and driving the
sync to arrange it would make the arrangement the thing most likely to
break them.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# The owner the authenticated test client and the MCP session both act as.
USER_ID = "test-user-123"

WORK_COLOUR = "#112233"
PERSONAL_COLOUR = "#445566"


async def create_calendar(
    connection: AsyncConnection,
    name: str,
    colour: str = "#336699",
    *,
    user_id: str = USER_ID,
) -> str:
    """A calendar row, as a string uuid."""
    calendar_id = uuid.uuid4()
    await connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, :name, :color)
        """),
        {
            "id": calendar_id,
            "user_id": user_id,
            "name": name,
            "color": colour,
        },
    )
    return str(calendar_id)


async def create_event_journal(
    connection: AsyncConnection,
    *,
    title: str,
    display_calendar_id: str,
    user_id: str = USER_ID,
) -> int:
    """An EVENT journal displayed in one calendar.

    A journal is an event because a ``journal_calendar_info`` row exists for
    it, which is also what names its display calendar.
    """
    start = datetime.now(UTC) + timedelta(days=3)
    result = await connection.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content,
                 event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, '', :start, :end)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "title": title,
            "start": start,
            "end": start + timedelta(hours=1),
        },
    )
    journal_id = int(result.scalar_one())

    await connection.execute(
        text("""
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day)
            VALUES (:journal_id, :calendar_id, false)
        """),
        {"journal_id": journal_id, "calendar_id": display_calendar_id},
    )
    return journal_id


async def link_calendar(
    connection: AsyncConnection,
    *,
    journal_id: int,
    calendar_id: str,
    external_event_id: str,
    sync_status: str = "synced",
) -> None:
    """The link a synced calendar holds for this event.

    ``sync_status='cancelled'`` is the shape left behind when the event is
    removed from *this* calendar while another still holds it: the link
    stays so the sync remembers the calendar, but the calendar no longer
    holds the event.
    """
    await connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id,
                 sync_capability, sync_status)
            VALUES (:journal_id, :calendar_id, :external_event_id,
                    'bidirectional', :sync_status)
        """),
        {
            "journal_id": journal_id,
            "calendar_id": calendar_id,
            "external_event_id": external_event_id,
            "sync_status": sync_status,
        },
    )


async def seed_shared_event(
    connection: AsyncConnection,
    *,
    title: str = "Physio appointment",
) -> tuple[int, str, str]:
    """One journal displayed in Work, also held by Personal.

    The shape de-duplication produces when a work calendar invites a
    personal one: a single journal, an external link per calendar, and one
    display calendar.

    Returns:
        ``(journal_id, work_calendar_id, personal_calendar_id)``
    """
    work = await create_calendar(connection, "Work", WORK_COLOUR)
    personal = await create_calendar(connection, "Personal", PERSONAL_COLOUR)
    journal_id = await create_event_journal(
        connection, title=title, display_calendar_id=work
    )
    await link_calendar(
        connection,
        journal_id=journal_id,
        calendar_id=work,
        external_event_id="work-copy-1",
    )
    await link_calendar(
        connection,
        journal_id=journal_id,
        calendar_id=personal,
        external_event_id="personal-copy-9",
    )
    return journal_id, work, personal
