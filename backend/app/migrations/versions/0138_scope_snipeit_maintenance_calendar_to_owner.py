"""give each user their own Snipe-IT maintenance calendar

Revision ID: 0138
Revises: 0137
Create Date: 2026-10-21 00:00:00.000000

Every user's imported Snipe-IT maintenances were linked on one synthetic
calendar, ``d7e0f8a1-…``, and a link is unique on ``(calendar_id,
external_event_id)``. Snipe-IT ids are per instance, so two users' instances
hand out the same ``snipeit_maint:{id}``: one user's link stood in for the
other's record, turning an import into an update of someone else's journal
(#1510). The worker now imports each user's records into their own calendar,
``uuid5(NAMESPACE_URL, "snipeit:maintenance:{user_id}")``.

For each owner with anything on the shared calendar this creates their calendar
and moves onto it their journals' links and calendar info, their series,
recurrence aliases and merged aliases, and the outbox events not yet relayed
that would otherwise recreate the shared calendar. A pending update the old
worker aimed at another owner's journal is sent as a create instead. The shared
calendar is then deleted. The ids are computed here, frozen, rather than imported from
``core_shared``: a migration must keep meaning what it meant when it ran.

Downgrading moves everything back onto the shared calendar, owned by one of the
users, refusing while two owners hold the same record id: the shared calendar's
key cannot represent that.
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import log

# revision identifiers, used by Alembic.
revision: str = "0138"
down_revision: str | None = "0137"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0138"
SHARED_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"
_SOURCE = "snipeit_maintenance"
_NAME = "Snipe-IT Maintenance"
_COLOR = "#808080"

# Each table referencing a calendar, and how its row's owner is found.
_JOURNAL_OWNED = ("journal_external_event_links", "journal_calendar_info")
_SELF_OWNED = (
    "journal_series",
    "journal_series_recurrence_aliases",
    "journal_merged_aliases",
)
# A pending journal sync event names its calendar twice.
_EVENT_ON_CALENDAR = (
    "relayed_at IS NULL AND event_type LIKE 'journal_event.%' "
    "AND CAST(event_data AS jsonb) ->> 'calendar_id' = :calendar_id"
)


def owner_calendar_id(user_id: str) -> str:
    """The Snipe-IT maintenance calendar of ``user_id``, as the worker names it."""
    return str(uuid5(NAMESPACE_URL, f"snipeit:maintenance:{user_id}"))


def _owners_on(connection: sa.Connection, calendar_id: str) -> list[str]:
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


def _move(
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
            """
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
              AND CAST(event_data AS jsonb) ->> 'calendar_id' = :source
              AND CAST(event_data AS jsonb) -> 'journal_data' ->> 'user_id' = :owner
            """
        ),
        params,
    )


def _create_calendar(connection: sa.Connection, calendar_id: str, owner: str) -> None:
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
            "name": _NAME,
            "color": _COLOR,
            "source": _SOURCE,
        },
    )


def _delete_calendar(connection: sa.Connection, calendar_id: str) -> None:
    connection.execute(
        sa.text("DELETE FROM calendars WHERE id = CAST(:id AS uuid)"),
        {"id": calendar_id},
    )


def _recreate_misdirected_updates(connection: sa.Connection) -> None:
    """Turn a pending update aimed at another owner's journal into a create.

    On the shared calendar the worker found another user's link for this user's
    record and queued an update of that user's journal. Moving the event to the
    owner's calendar leaves that target in place, so the update would still try
    to rewrite someone else's journal. It is sent as the create it should have
    been. An update of the owner's own journal, or of one since deleted, keeps
    its target and is handled as before.
    """
    connection.execute(
        sa.text(
            """
            UPDATE outbox_events o
            SET event_type = 'journal_event.created',
                event_data = CAST(
                    jsonb_set(
                        jsonb_set(CAST(o.event_data AS jsonb),
                                  '{existing_journal_id}', 'null'::jsonb),
                        '{sync_action}', '"created"'::jsonb
                    ) AS text)
            WHERE o.relayed_at IS NULL
              AND o.event_type = 'journal_event.updated'
              AND CAST(o.event_data AS jsonb) ->> 'calendar_id' = :shared
              AND EXISTS (
                  SELECT 1 FROM journals j
                  WHERE j.id = CAST(
                          CAST(o.event_data AS jsonb) ->> 'existing_journal_id'
                          AS integer)
                    AND j.user_id IS DISTINCT FROM
                        CAST(o.event_data AS jsonb) -> 'journal_data' ->> 'user_id'
              )
            """
        ),
        {"shared": SHARED_CALENDAR_ID},
    )


def upgrade() -> None:
    """Move every owner's maintenance rows onto their own calendar."""
    connection = op.get_bind()
    _recreate_misdirected_updates(connection)
    owners = _owners_on(connection, SHARED_CALENDAR_ID)
    for owner in owners:
        target = owner_calendar_id(owner)
        _create_calendar(connection, target, owner)
        _move(connection, owner=owner, source_id=SHARED_CALENDAR_ID, target_id=target)
        log.info("%s: moved %s's Snipe-IT maintenances to %s.", _LABEL, owner, target)
    _delete_calendar(connection, SHARED_CALENDAR_ID)


def downgrade() -> None:
    """Move everything back onto the shared calendar, refusing a shared record id."""
    connection = op.get_bind()
    calendars = connection.execute(
        sa.text(
            "SELECT CAST(id AS text) AS id, user_id FROM calendars "
            "WHERE integration_source = :source AND id <> CAST(:shared AS uuid) "
            "ORDER BY user_id"
        ),
        {"source": _SOURCE, "shared": SHARED_CALENDAR_ID},
    ).fetchall()
    if not calendars:
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
            f"{_LABEL} cannot be downgraded: {len(shared)} Snipe-IT maintenances "
            f"are linked by more than one owner ({ids}), which one shared calendar "
            "cannot hold. Remove all but one owner's link for each first."
        )

    _create_calendar(connection, SHARED_CALENDAR_ID, calendars[0].user_id)
    for row in calendars:
        _move(
            connection,
            owner=row.user_id,
            source_id=row.id,
            target_id=SHARED_CALENDAR_ID,
        )
        _delete_calendar(connection, row.id)
