"""SQL adapter for the agenda's windowed read.

**One statement, whatever the day holds.** Tags and participants are both
many-per-journal, so joining either directly multiplies the journal's row by its
children and joining both multiplies them by each other; and reading them per
journal afterwards is the N+1 the phase's acceptance criterion exists to forbid.
Each is therefore aggregated in its own ``LATERAL`` sub-select, which keeps
exactly one row per journal however many tags or attendees it has. An integration
test counts the statements, because functionally an N+1 is invisible — the answer
is right either way and only the number of round trips is wrong.

The window predicate is the outdoor dashboard's, and it is an **overlap**: an
event that began before the day and ends after it is on today's agenda, because
it is happening. Containment would silently drop every multi-day trip from the
day in the middle of it.

Scoped on ``journals.user_id``. Tags and contacts carry no owner of their own in
this schema, so reachability through the user's own journal is the scope, and the
join can only reach rows attached to a journal that has already been filtered.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core_shared.models.journals.event_state import EventState
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from sqlalchemy import text

from app.core.dashboard.models.repositories import AgendaRepository
from app.core.dashboard.models.sections import (
    AgendaEntry,
    AgendaParticipant,
    AgendaTag,
)

if TYPE_CHECKING:
    from core_shared.models.journals import EventDateRange
    from sqlalchemy.ext.asyncio import AsyncConnection

# Both ways of being *at* an event. The journal's own contact badge treats these
# two as attendance, and the Google worker writes every synced attendee as
# INVITEE — so taking only PARTICIPANT would empty the avatar stack on exactly
# the events most users have most of. MENTION and ABOUT are people the journal is
# about, who were never claimed to be there.
#
# Taking two types makes the aggregate need DISTINCT: the relationship table's
# key is (journal, contact, type), so one contact can hold both and would
# otherwise be drawn twice in the avatar stack with an inflated overflow count.
# A contact merge reaches that state on its own — its dedupe is per type.
_ATTENDING = (
    JournalContactRelationshipType.PARTICIPANT.value,
    JournalContactRelationshipType.INVITEE.value,
)

# ``::text`` on both aggregates so the driver hands back a string either way and
# this module does the parsing, rather than behaving differently depending on
# whether the connection has a JSON codec registered.
_ENTRIES_QUERY = text(
    """
    SELECT
        j.id AS journal_id,
        j.title AS title,
        j.event_date_range_start AS starts_at,
        j.event_date_range_end AS ends_at,
        jci.is_all_day AS is_all_day,
        jci.start_time AS start_time,
        jci.end_time AS end_time,
        jci.location AS location,
        jci.timezone AS timezone,
        jci.event_state AS event_state,
        COALESCE(tags.items, '[]'::json)::text AS tags,
        COALESCE(attendees.items, '[]'::json)::text AS participants
    FROM journals j
    JOIN journal_calendar_info jci ON jci.journal_id = j.id
    LEFT JOIN LATERAL (
        SELECT json_agg(
                   json_build_object('id', t.id, 'name', t.name, 'colour', t.color)
                   ORDER BY t.name, t.id
               ) AS items
        FROM journal_tag_assignments a
        JOIN journal_tags t ON t.id = a.tag_id
        WHERE a.journal_id = j.id
    ) tags ON TRUE
    LEFT JOIN LATERAL (
        SELECT json_agg(
                   json_build_object('contact_id', person.id, 'name', person.name)
                   ORDER BY person.name, person.id
               ) AS items
        FROM (
            SELECT DISTINCT
                c.id AS id,
                concat_ws(' ', c.first_name, c.last_name) AS name
            FROM journal_contact_relationships r
            JOIN contacts c ON c.id = r.contact_id
            WHERE r.journal_id = j.id
              AND r.relationship_type = ANY(:attending)
        ) person
    ) attendees ON TRUE
    WHERE j.user_id = :user_id
      AND j.event_date_range_end >= :window_start
      AND j.event_date_range_start <= :window_end
    ORDER BY j.event_date_range_start, j.id
    """
)


class SqlAgendaRepository(AgendaRepository):
    """Reads agenda entries with SQLAlchemy Core over the request's connection."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialise the repository with a database connection."""
        self.conn = connection

    async def list_entries_in_window(
        self, user_id: str, *, window: EventDateRange
    ) -> list[AgendaEntry]:
        """The user's event journals overlapping ``window``, tags and all."""
        result = await self.conn.execute(
            _ENTRIES_QUERY,
            {
                "user_id": user_id,
                "window_start": window.start,
                "window_end": window.end,
                "attending": list(_ATTENDING),
            },
        )
        return [_to_entry(row) for row in result.mappings()]


def _to_entry(row: Any) -> AgendaEntry:
    """One result row as an agenda entry.

    ``event_state`` is collapsed to a single boolean here rather than carried
    across: cancellation is the only part of that vocabulary the agenda has a
    rule about, and the rest of it is calendar-sync state that a dashboard card
    would have to invent a meaning for.
    """
    return AgendaEntry(
        journal_id=row["journal_id"],
        title=row["title"],
        is_all_day=row["is_all_day"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        location=row["location"],
        timezone=row["timezone"],
        is_cancelled=row["event_state"] == EventState.CANCELLED.value,
        tags=tuple(
            AgendaTag(id=str(tag["id"]), name=tag["name"], colour=tag["colour"])
            for tag in json.loads(row["tags"])
        ),
        participants=tuple(
            AgendaParticipant(contact_id=person["contact_id"], name=person["name"])
            for person in json.loads(row["participants"])
        ),
    )
