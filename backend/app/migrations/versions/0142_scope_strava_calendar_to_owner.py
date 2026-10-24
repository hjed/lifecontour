"""give each user their own Strava calendar

Revision ID: 0142
Revises: 0141
Create Date: 2026-10-24 00:00:00.000000

Every user's imported Strava activities were linked on one synthetic calendar,
``00000000-…-0001``. The backend creates such a calendar the first time an event
names it, owned by that event's user, so it belonged to whoever synced first:
only they saw "Strava Activities" in their calendar list, and it held everyone
else's journals (#1856). The worker now links each user's activities on their
own calendar, ``uuid5(NAMESPACE_URL, "strava:{user_id}")``.

For each owner with anything on the shared calendar this creates their calendar
and moves onto it their journals' links and calendar info, their series,
recurrence aliases and merged aliases, and the outbox events not yet relayed
that would otherwise recreate the shared calendar. The shared calendar is then
deleted. A link the new worker already made on the owner's calendar, when it ran
before this migration, supersedes the shared one. Strava activity ids are
globally unique and the worker only ever updated a journal it found for the
syncing user, so unlike ``0138`` no pending update aims at another owner's
journal. The ids are computed here, frozen, rather than imported from
``core_shared``: a migration must keep meaning what it meant when it ran.

Downgrading moves everything back onto the shared calendar, owned by one of the
users, refusing while two owners link the same activity (two accounts connected
to one athlete): the shared calendar's key cannot represent that.
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

from app.migrations.synthetic_calendar_scoping import (
    SyntheticCalendarSpec,
    owners_on,
    return_to_shared,
    scope_to_owners,
)

# revision identifiers, used by Alembic.
revision: str = "0142"
down_revision: str | None = "0141"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHARED_CALENDAR_ID = "00000000-0000-0000-0000-000000000001"


def owner_calendar_id(user_id: str) -> str:
    """The Strava calendar of ``user_id``, as the worker names it."""
    return str(uuid5(NAMESPACE_URL, f"strava:{user_id}"))


_CALENDAR = SyntheticCalendarSpec(
    label="0142",
    shared_id=SHARED_CALENDAR_ID,
    integration_source="strava",
    name="Strava Activities",
    color="#FC4C02",
    owner_calendar_id=owner_calendar_id,
    records="Strava activities",
)


def _drop_links_superseded_on_own_calendar(connection: sa.Connection) -> None:
    """Drop a shared-calendar link whose journal is already linked on its own.

    The new worker can run before this migration does. The backend still on the
    old revision then applies its update of an imported activity on the user's
    own calendar, linking the journal there beside its shared-calendar link,
    and moving the older link would collide with it. The newer one stands.
    """
    for owner in owners_on(connection, SHARED_CALENDAR_ID):
        connection.execute(
            sa.text(
                """
                DELETE FROM journal_external_event_links shared
                USING journals j
                WHERE shared.calendar_id = CAST(:shared AS uuid)
                  AND j.id = shared.journal_id
                  AND j.user_id = :owner
                  AND EXISTS (
                      SELECT 1 FROM journal_external_event_links own
                      WHERE own.journal_id = shared.journal_id
                        AND own.calendar_id = CAST(:own AS uuid)
                  )
                """
            ),
            {
                "shared": SHARED_CALENDAR_ID,
                "owner": owner,
                "own": owner_calendar_id(owner),
            },
        )


def upgrade() -> None:
    """Move every owner's Strava rows onto their own calendar."""
    connection = op.get_bind()
    _drop_links_superseded_on_own_calendar(connection)
    scope_to_owners(connection, _CALENDAR)


def downgrade() -> None:
    """Move everything back onto the shared calendar, refusing a shared activity."""
    return_to_shared(op.get_bind(), _CALENDAR)
