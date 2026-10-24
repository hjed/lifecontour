"""Move an integration's records off one shared synthetic calendar, one per owner.

Integrations with no calendars of their own (Strava, Snipe-IT) link imported
journals on a synthetic calendar. They began with one calendar for every user,
owned by whoever synced first and hidden from everyone else; a link is unique per
calendar, so it was also a cross-user key (#1510, #1856). Each now links a
user's records on that user's own calendar, and a migration moving onto it uses
this module.

Every table referencing ``calendars.id`` is moved, with the outbox events not yet
relayed that would otherwise recreate the shared calendar when applied. A
revision computes its own owner ids and passes them in, frozen, rather than
importing the worker's helper. This module is shared by several revisions, so
treat its behaviour as frozen once a revision depends on it: change it only by
adding, never by redefining.
"""

from collections.abc import Callable
from dataclasses import dataclass

import sqlalchemy as sa

from app.migrations.owner_derivation import log

# Each table referencing a calendar, and how its row's owner is found.
_JOURNAL_OWNED = ("journal_external_event_links", "journal_calendar_info")
_SELF_OWNED = (
    "journal_series",
    "journal_series_recurrence_aliases",
    "journal_merged_aliases",
)
# A pending journal sync event names its calendar twice; this points both at
# ``:target``.
_RECALENDAR_PENDING_EVENTS = """
    UPDATE outbox_events
    SET event_data = CAST(
        jsonb_set(
            jsonb_set(CAST(event_data AS jsonb), '{calendar_id}',
                      to_jsonb(CAST(:target AS text))),
            '{calendar_info_data,calendar_id}',
            to_jsonb(CAST(:target AS text)),
            false
        ) AS text)
    WHERE relayed_at IS NULL
      AND event_type LIKE 'journal_event.%'
"""
_EVENT_ON_CALENDAR = (
    "relayed_at IS NULL AND event_type LIKE 'journal_event.%' "
    "AND CAST(event_data AS jsonb) ->> 'calendar_id' = :calendar_id"
)


@dataclass(frozen=True)
class SyntheticCalendarSpec:
    """One integration's synthetic calendar, as a migration moves it."""

    label: str  # the revision, for log lines and errors
    shared_id: str
    integration_source: str
    name: str
    color: str
    owner_calendar_id: Callable[[str], str]
    records: str  # what the calendar holds, plural, for the downgrade's refusal


def owners_on(connection: sa.Connection, calendar_id: str) -> list[str]:
    """Everyone with a row or pending event on ``calendar_id``."""
    branches = [
        f"SELECT j.user_id FROM {table} t JOIN journals j ON j.id = t.journal_id "
        "WHERE t.calendar_id = CAST(:calendar_id AS uuid)"
        for table in _JOURNAL_OWNED
    ]
    branches += [
        f"SELECT user_id FROM {table} WHERE calendar_id = CAST(:calendar_id AS uuid)"
        for table in _SELF_OWNED
    ]
    branches.append(
        "SELECT CAST(event_data AS jsonb) -> 'journal_data' ->> 'user_id' "
        f"FROM outbox_events WHERE {_EVENT_ON_CALENDAR}"
    )
    rows = connection.execute(
        sa.text(" UNION ".join(branches)),  # noqa: S608 - module constants only
        {"calendar_id": calendar_id},
    )
    return sorted(row[0] for row in rows if row[0] is not None)


def move_owner_rows(
    connection: sa.Connection, *, owner: str, source_id: str, target_id: str
) -> None:
    """Move ``owner``'s rows and pending events from one calendar to another."""
    params = {"owner": owner, "source": source_id, "target": target_id}
    for table in _JOURNAL_OWNED:
        connection.execute(
            sa.text(
                f"UPDATE {table} t SET calendar_id = CAST(:target AS uuid) "  # noqa: S608
                "FROM journals j WHERE j.id = t.journal_id AND j.user_id = :owner "
                "AND t.calendar_id = CAST(:source AS uuid)"
            ),
            params,
        )
    for table in _SELF_OWNED:
        connection.execute(
            sa.text(
                f"UPDATE {table} SET calendar_id = CAST(:target AS uuid) "  # noqa: S608
                "WHERE user_id = :owner AND calendar_id = CAST(:source AS uuid)"
            ),
            params,
        )
    connection.execute(
        sa.text(
            _RECALENDAR_PENDING_EVENTS
            + "AND CAST(event_data AS jsonb) ->> 'calendar_id' = :source "
            "AND CAST(event_data AS jsonb) -> 'journal_data' ->> 'user_id' = :owner"
        ),
        params,
    )


def _create_calendar(
    connection: sa.Connection, spec: SyntheticCalendarSpec, calendar_id: str, owner: str
) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO calendars (id, user_id, name, color, integration_source)
            VALUES (CAST(:id AS uuid), :owner, :name, :color, :source)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": calendar_id,
            "owner": owner,
            "name": spec.name,
            "color": spec.color,
            "source": spec.integration_source,
        },
    )


def _delete_calendar(connection: sa.Connection, calendar_id: str) -> None:
    connection.execute(
        sa.text("DELETE FROM calendars WHERE id = CAST(:id AS uuid)"),
        {"id": calendar_id},
    )


def scope_to_owners(connection: sa.Connection, spec: SyntheticCalendarSpec) -> None:
    """Move every owner's rows onto their own calendar and drop the shared one."""
    for owner in owners_on(connection, spec.shared_id):
        target = spec.owner_calendar_id(owner)
        _create_calendar(connection, spec, target, owner)
        move_owner_rows(
            connection, owner=owner, source_id=spec.shared_id, target_id=target
        )
        log.info("%s: moved %s's %s to %s.", spec.label, owner, spec.records, target)
    _delete_calendar(connection, spec.shared_id)


def _return_pending_events(
    connection: sa.Connection, spec: SyntheticCalendarSpec
) -> None:
    """Point every pending event of the integration at the shared calendar.

    A user's first import can exist only as an event: its calendar is created
    when the event is applied, so no calendar row names it yet. Applied after
    the downgrade, it would link the journal on a calendar the old worker never
    looks at, and the next sync would import the record again.
    """
    connection.execute(
        sa.text(
            _RECALENDAR_PENDING_EVENTS
            + "AND CAST(event_data AS jsonb) ->> 'integration_source' = :source "
            "AND CAST(event_data AS jsonb) ->> 'calendar_id' <> :target"
        ),
        {"source": spec.integration_source, "target": spec.shared_id},
    )


def return_to_shared(connection: sa.Connection, spec: SyntheticCalendarSpec) -> None:
    """Move everything back onto the shared calendar, refusing a shared record id.

    The shared calendar is owned by the first owner, as the old worker left it.
    Two owners linking the same record cannot both stand on one calendar, so
    the downgrade refuses rather than drop one of them.
    """
    calendars = connection.execute(
        sa.text(
            "SELECT CAST(id AS text) AS id, user_id FROM calendars "
            "WHERE integration_source = :source AND id <> CAST(:shared AS uuid) "
            "ORDER BY user_id"
        ),
        {"source": spec.integration_source, "shared": spec.shared_id},
    ).fetchall()
    if not calendars:
        _return_pending_events(connection, spec)
        return

    shared = connection.execute(
        sa.text(
            """
            SELECT external_event_id FROM journal_external_event_links
            WHERE calendar_id = ANY(CAST(:ids AS uuid[]))
              AND external_event_id IS NOT NULL
            GROUP BY external_event_id
            HAVING count(*) > 1
            ORDER BY external_event_id
            """
        ),
        {"ids": [row.id for row in calendars]},
    ).fetchall()
    if shared:
        ids = ", ".join(row.external_event_id for row in shared)
        raise RuntimeError(
            f"{spec.label} cannot be downgraded: {len(shared)} {spec.records} "
            f"are linked by more than one owner ({ids}), which one shared calendar "
            "cannot hold. Remove all but one owner's link for each first."
        )

    _create_calendar(connection, spec, spec.shared_id, calendars[0].user_id)
    for row in calendars:
        move_owner_rows(
            connection,
            owner=row.user_id,
            source_id=row.id,
            target_id=spec.shared_id,
        )
        _delete_calendar(connection, row.id)
    _return_pending_events(connection, spec)
