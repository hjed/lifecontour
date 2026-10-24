"""force one full Google contacts sync so countryless addresses are imported

Revision ID: 0141
Revises: 0140
Create Date: 2026-10-21 00:00:00.000000

Google contacts sync now imports an address with no country, giving it the
contact's phone country or the user's default country (#1820). Before, every
such address was skipped - but the processor skips a person whose etag has not
moved, so a contact Google has not changed since would never receive it.

Clearing each account's contacts sync token makes the next smart sync a full
sync, whose events are applied whatever their etag (``force_apply``). Each
applied event also records the address fallback it used on the link, which is
what lets a push own those addresses; until a person's event is applied the
push keeps them in Google. The push that runs first in the same job is
unaffected.

The downgrade is a no-op: a cleared token only costs one full sync.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0141"
down_revision: str | Sequence[str] | None = "0140"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Clear every contacts sync token so the next Google sync is a full one."""
    op.execute("UPDATE user_google_integration SET contacts_sync_token = NULL")


def downgrade() -> None:
    """Nothing to restore: the next incremental sync stores a fresh token."""
