"""Create journals table

Revision ID: 0009
Revises: 0008
Create Date: 2024-12-07 12:00:00.000000

This migration creates the base journals table for the journal domain.
The table supports hierarchical structure with parent-child relationships.

Note: user_id uses VARCHAR(50) without FK constraint as users table
doesn't exist yet. FK should be added when users table is created.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journals table with indexes and constraints."""

    # Create journals table
    op.create_table(
        "journals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.VARCHAR(length=50),
            nullable=False,
            comment="User identifier (FK to users when table exists)",
        ),
        sa.Column(
            "title",
            sa.VARCHAR(length=500),
            nullable=False,
            comment="Journal title (max 500 characters)",
        ),
        sa.Column(
            "content",
            sa.TEXT(),
            nullable=False,
            comment="Markdown content of the journal entry",
        ),
        sa.Column(
            "event_date_range_start",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Start of the event date range (UTC)",
        ),
        sa.Column(
            "event_date_range_end",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="End of the event date range (UTC)",
        ),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="SET NULL"),
            nullable=True,
            comment="Parent journal ID for hierarchy (max depth 5)",
        ),
        sa.Column(
            "order",
            sa.Integer(),
            nullable=True,
            comment="Order among siblings for manual sorting",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Record creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Record last update timestamp",
        ),
        sa.PrimaryKeyConstraint("id"),
        # Constraint: event_date_range.start must be <= event_date_range.end
        sa.CheckConstraint(
            "event_date_range_start <= event_date_range_end",
            name="ck_journals_event_date_range_valid",
        ),
    )

    # Create indexes for performance
    # Index on user_id for filtering by user
    op.create_index("idx_journals_user_id", "journals", ["user_id"])

    # Index on parent_id for hierarchy queries
    op.create_index("idx_journals_parent_id", "journals", ["parent_id"])

    # Index on event_date_range for date-based queries
    op.create_index(
        "idx_journals_event_date_range",
        "journals",
        ["event_date_range_start", "event_date_range_end"],
    )

    # Index for ordering children (by date, then order)
    op.create_index(
        "idx_journals_child_ordering",
        "journals",
        ["parent_id", "event_date_range_start", "order"],
    )

    # Index on created_at for recent journals query
    op.create_index("idx_journals_created_at", "journals", ["created_at"])


def downgrade() -> None:
    """Drop journals table and indexes."""

    # Drop indexes
    op.drop_index("idx_journals_created_at", table_name="journals")
    op.drop_index("idx_journals_child_ordering", table_name="journals")
    op.drop_index("idx_journals_event_date_range", table_name="journals")
    op.drop_index("idx_journals_parent_id", table_name="journals")
    op.drop_index("idx_journals_user_id", table_name="journals")

    # Drop table
    op.drop_table("journals")
