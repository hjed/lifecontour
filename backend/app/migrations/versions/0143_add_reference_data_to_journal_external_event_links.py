"""add reference_data to journal_external_event_links

Revision ID: 0143
Revises: 0142
Create Date: 2026-10-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0143"
down_revision: str | None = "0142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give a calendar link somewhere to keep its synced base (#1899).

    The journal push merges against what both sides last agreed on, per event
    field (``core_shared.calendar_sync_base``), so it can leave alone a field
    Google changed since. Contacts keep theirs in
    ``sync_metadata.reference_data``; calendar links have no such row, so the
    same JSON text goes on the link itself, read with ``core_shared.sync_base``.

    Nullable: existing links record no base until their next applied pull or
    push, and fall back on today's behaviour until then.
    """
    op.add_column(
        "journal_external_event_links",
        sa.Column("reference_data", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop the reference_data column."""
    op.drop_column("journal_external_event_links", "reference_data")
