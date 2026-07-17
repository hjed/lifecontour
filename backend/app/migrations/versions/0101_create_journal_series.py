"""create journal_series and journal_series_members tables

Revision ID: 0101
Revises: 0100
Create Date: 2026-07-14 09:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0101"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the journal series grouping tables.

    A series groups related journal entries — either auto-created from a Google
    Calendar recurring event (keyed by ``calendar_id`` + ``recurring_event_id``)
    or created manually via UI/MCP (both keys NULL). A journal may belong to
    multiple series.
    """
    op.create_table(
        "journal_series",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("calendar_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("recurring_event_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["calendars.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Get-or-create key for auto-created series: one series per recurring
    # master event per calendar. Manual series have NULL keys and are exempt.
    op.create_index(
        "uq_journal_series_recurrence",
        "journal_series",
        ["calendar_id", "recurring_event_id"],
        unique=True,
        postgresql_where=sa.text("recurring_event_id IS NOT NULL"),
    )
    op.create_index("ix_journal_series_user_id", "journal_series", ["user_id"])

    op.create_table(
        "journal_series_members",
        sa.Column("series_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["journal_series.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["journal_id"],
            ["journals.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("series_id", "journal_id"),
    )
    op.create_index(
        "ix_journal_series_members_journal_id",
        "journal_series_members",
        ["journal_id"],
    )


def downgrade() -> None:
    """Drop the journal series tables."""
    op.drop_index(
        "ix_journal_series_members_journal_id",
        table_name="journal_series_members",
    )
    op.drop_table("journal_series_members")
    op.drop_index("ix_journal_series_user_id", table_name="journal_series")
    op.drop_index("uq_journal_series_recurrence", table_name="journal_series")
    op.drop_table("journal_series")
