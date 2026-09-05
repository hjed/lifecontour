"""SQL adapter for the agenda's windowed read.

**One statement, whatever the day holds.** Tags and participants are both
many-per-journal, so joining either directly multiplies the journal's row by its
children and joining both multiplies them by each other; and reading them per
journal afterwards is the N+1 the phase's acceptance criterion exists to forbid.
Each is therefore aggregated in its own ``LATERAL`` sub-select, which keeps
exactly one row per journal however many tags or attendees it has. An integration
test counts the statements, because functionally an N+1 is invisible — the answer
is right either way and only the number of round trips is wrong.

**A timed event is matched by instant overlap; an all-day event is matched by
date.** The overlap predicate is the outdoor dashboard's: an event that began
before the day and ends after it is on today's agenda, because it is happening,
and containment would silently drop every multi-day trip from the day in the
middle of it.

All-day events cannot use it. They happen on a *date* and the schema stores only
instants, and the two writers disagree about which instant means that date: the
Google worker stores midnight **UTC** with no event timezone
(``_parse_all_day_date``), while the app stores midnight in the **browser's**
zone with ``timezone`` set to the user's. Under instant overlap a Google-synced
all-day event on 27 August is the instant ``2026-08-27T00:00Z``, which for a user
west of UTC falls in their **26 August** window — so synced public holidays and
out-of-office days show a day early.

Reading the bounds back **in the zone they were written in** recovers the
intended date from both conventions, and it is the rule the codebase already uses
elsewhere (``event_date_in_timezone``, and migration 0045 for the clock columns).
Google's rows carry no zone, so they are read as UTC, which is what they are; the
app's carry the user's, so local midnight reads back as midnight.

**The zone is resolved through ``pg_timezone_names`` rather than used directly**,
because the column takes any string and ``AT TIME ZONE`` *raises* on one
PostgreSQL does not recognise — which would abort the statement and cost the
whole section, so a single legacy or externally-synced row with a nonsense zone
would empty an otherwise good day. The join turns an unrecognised name into
``NULL`` and the ``COALESCE`` reads it as UTC, which is the same fallback
``resolve_timezone`` gives the anchor and ``CalendarInfo`` hydration gives a
persisted row. ``pg_timezone_names.name`` is unique, so the join cannot fan the
row out.

**One case is knowingly not served**, and is recorded in the iteration document:
an app-created all-day row whose ``timezone`` was *cleared* has a local-midnight
instant and no zone to read it in, so it is read as UTC and lands a day early for
a user east of UTC. That is narrower than the defect this fixes — it needs a
deliberate edit to a rarely-touched field — and the follow-up is to default the
zone at the write path so the case disappears.

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

from app.core.journal.models.agenda import (
    AgendaEntry,
    AgendaParticipant,
    AgendaTag,
)
from app.core.journal.models.repositories import AgendaRepository

if TYPE_CHECKING:
    from datetime import date

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
        cal.color AS calendar_color,
        jci.event_state AS event_state,
        COALESCE(tags.items, '[]'::json)::text AS tags,
        COALESCE(attendees.items, '[]'::json)::text AS participants
    FROM journals j
    JOIN journal_calendar_info jci ON jci.journal_id = j.id
    -- LEFT rather than INNER: the FK is NOT NULL, but a row's accent colour is
    -- decoration and an unexpectedly missing calendar must not drop an event
    -- off somebody's day.
    LEFT JOIN calendars cal ON cal.id = jci.calendar_id
    -- Resolves the stored zone to one PostgreSQL will accept, or to NULL. Never
    -- feed jci.timezone to AT TIME ZONE directly: it raises on an unrecognised
    -- name, and one bad row would abort the read for the whole day.
    LEFT JOIN pg_timezone_names tz ON tz.name = jci.timezone
    LEFT JOIN LATERAL (
        SELECT json_agg(
                   json_build_object('id', t.id, 'name', t.name, 'color', t.color)
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
      AND CASE WHEN jci.is_all_day THEN
              (j.event_date_range_start
                   AT TIME ZONE COALESCE(tz.name, 'UTC'))::date <= :anchor
              AND (j.event_date_range_end
                   AT TIME ZONE COALESCE(tz.name, 'UTC'))::date >= :anchor
          ELSE
              j.event_date_range_end >= :window_start
              AND j.event_date_range_start <= :window_end
          END
    ORDER BY j.event_date_range_start, j.id
    """
)


class SqlAgendaRepository(AgendaRepository):
    """Reads agenda entries with SQLAlchemy Core over the request's connection."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialise the repository with a database connection."""
        self.conn = connection

    async def list_entries_in_window(
        self, user_id: str, *, window: EventDateRange, anchor: date
    ) -> list[AgendaEntry]:
        """The user's event journals for the day, tags and all."""
        result = await self.conn.execute(
            _ENTRIES_QUERY,
            {
                "user_id": user_id,
                "window_start": window.start,
                "window_end": window.end,
                "anchor": anchor,
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
        calendar_color=row["calendar_color"],
        is_cancelled=row["event_state"] == EventState.CANCELLED.value,
        tags=tuple(
            AgendaTag(id=str(tag["id"]), name=tag["name"], color=tag["color"])
            for tag in json.loads(row["tags"])
        ),
        participants=tuple(
            AgendaParticipant(contact_id=person["contact_id"], name=person["name"])
            for person in json.loads(row["participants"])
        ),
    )
