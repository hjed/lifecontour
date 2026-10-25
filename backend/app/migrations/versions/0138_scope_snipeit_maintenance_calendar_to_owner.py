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

from app.migrations.synthetic_calendar_scoping import (
    SyntheticCalendarSpec,
    return_to_shared,
    scope_to_owners,
)

# revision identifiers, used by Alembic.
revision: str = "0138"
down_revision: str | None = "0137"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHARED_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"


def owner_calendar_id(user_id: str) -> str:
    """The Snipe-IT maintenance calendar of ``user_id``, as the worker names it."""
    return str(uuid5(NAMESPACE_URL, f"snipeit:maintenance:{user_id}"))


_CALENDAR = SyntheticCalendarSpec(
    label="0138",
    shared_id=SHARED_CALENDAR_ID,
    integration_source="snipeit_maintenance",
    name="Snipe-IT Maintenance",
    color="#808080",
    owner_calendar_id=owner_calendar_id,
    records="Snipe-IT maintenances",
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
    scope_to_owners(connection, _CALENDAR)


def downgrade() -> None:
    """Move everything back onto the shared calendar, refusing a shared record id."""
    return_to_shared(op.get_bind(), _CALENDAR)
