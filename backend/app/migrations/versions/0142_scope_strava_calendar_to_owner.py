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
deleted. The worker keeps naming the shared calendar for as long as its row
exists, so nothing is linked on an owner's own calendar before this runs, even
when the new worker is deployed first. Strava activity ids are globally unique
and the worker only ever updated a journal it found for the syncing user, so
unlike ``0138`` no pending update aims at another owner's journal. The ids are
computed here, frozen, rather than imported from ``core_shared``: a migration
must keep meaning what it meant when it ran.

Downgrading moves everything back onto the shared calendar, owned by one of the
users, refusing while two owners link the same activity (two accounts connected
to one athlete): the shared calendar's key cannot represent that.
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from alembic import op

from app.migrations.synthetic_calendar_scoping import (
    SyntheticCalendarSpec,
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


def upgrade() -> None:
    """Move every owner's Strava rows onto their own calendar."""
    scope_to_owners(op.get_bind(), _CALENDAR)


def downgrade() -> None:
    """Move everything back onto the shared calendar, refusing a shared activity."""
    return_to_shared(op.get_bind(), _CALENDAR)
