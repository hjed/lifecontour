"""create journal_series_recurrence_aliases table

Revision ID: 0121
Revises: 0120
Create Date: 2026-09-29 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0121"
down_revision: str | None = "0120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the recurrence alias table used when series are merged.

    Calendar sync get-or-creates a series per ``(calendar_id,
    recurring_event_id)``. When an auto-created series is merged into another,
    its recurrence key is recorded here against the surviving series so the
    next sync of that recurrence adds its instances to the survivor instead of
    re-creating the merged-away series. Deleting the survivor drops its
    aliases, the same outcome as deleting any recurring series.
    """
    op.create_table(
        "journal_series_recurrence_aliases",
        sa.Column("calendar_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recurring_event_id", sa.String(length=255), nullable=False),
        sa.Column("series_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["calendars.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["journal_series.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("calendar_id", "recurring_event_id"),
    )
    op.create_index(
        "ix_journal_series_recurrence_aliases_series_id",
        "journal_series_recurrence_aliases",
        ["series_id"],
    )


def downgrade() -> None:
    """Drop the recurrence alias table."""
    op.drop_index(
        "ix_journal_series_recurrence_aliases_series_id",
        table_name="journal_series_recurrence_aliases",
    )
    op.drop_table("journal_series_recurrence_aliases")
