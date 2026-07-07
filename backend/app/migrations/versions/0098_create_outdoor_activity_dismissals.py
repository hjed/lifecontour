"""create outdoor_activity_dismissals table

Revision ID: 0098
Revises: 0097
Create Date: 2026-07-07 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0098"
down_revision: str | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the journal-scoped outdoor-activity dismissal store.

    Records that a user has dismissed an outdoor activity journal from the
    incomplete-activities review. Distinct from the merge ``journal_review_items``
    queue. A row's presence means the journal is dismissed; ``provenance`` records
    where the dismissal came from (UI / MCP / ...).
    """
    op.create_table(
        "outdoor_activity_dismissals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
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
            ["journal_id"],
            ["journals.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "journal_id",
            name="uq_outdoor_activity_dismissals_user_journal",
        ),
    )
    # The composite unique constraint (user_id, journal_id) already indexes
    # user_id as its leftmost prefix, so per-user lookups
    # (list_dismissed_journal_ids) are served without a separate index.


def downgrade() -> None:
    """Drop the outdoor_activity_dismissals table."""
    op.drop_table("outdoor_activity_dismissals")
