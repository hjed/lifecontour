"""force one full Google contacts sync so nicknames are imported

Revision ID: 0131
Revises: 0130
Create Date: 2026-10-10 00:00:00.000000

Google contacts sync now imports nicknames. It always pushed them, so Google
still holds every nickname the old import cleared - but the processor skips a
person whose etag has not moved, so a contact Google has not changed since would
never receive its nickname back.

Clearing each account's contacts sync token makes the next smart sync a full
sync, whose events are applied whatever their etag (``force_apply``). The push
that runs first in the same job is unaffected: the sync links, and the etags it
sends for concurrency, are left alone.

The downgrade is a no-op: a cleared token only costs one full sync.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0131"
down_revision: str | Sequence[str] | None = "0130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Clear every contacts sync token so the next Google sync is a full one."""
    op.execute("UPDATE user_google_integration SET contacts_sync_token = NULL")


def downgrade() -> None:
    """Nothing to restore: the next incremental sync stores a fresh token."""
