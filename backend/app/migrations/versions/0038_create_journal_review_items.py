"""create journal review items table

Revision ID: 0038
Revises: 0037
Create Date: 2026-03-17

Adds the journal_review_items table for the match candidate review queue.
Review items link a newly created journal to a potential duplicate,
surfacing them for user review rather than auto-merging.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_review_items table."""
    op.create_table(
        "journal_review_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.VARCHAR(length=255), nullable=False),
        sa.Column(
            "source_journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.VARCHAR(length=50), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("details", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('external_link_match', 'duplicate_journal', 'needs_review')",
            name="ck_journal_review_items_reason",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'dismissed')",
            name="ck_journal_review_items_status",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_journal_review_items_confidence_score",
        ),
        sa.CheckConstraint(
            "source_journal_id != candidate_journal_id",
            name="ck_journal_review_items_different_journals",
        ),
        sa.UniqueConstraint(
            "source_journal_id",
            "candidate_journal_id",
            name="uq_journal_review_items_source_candidate",
        ),
    )
    op.create_index(
        "ix_journal_review_items_source_journal_id",
        "journal_review_items",
        ["source_journal_id"],
    )
    op.create_index(
        "ix_journal_review_items_candidate_journal_id",
        "journal_review_items",
        ["candidate_journal_id"],
    )
    op.create_index(
        "ix_journal_review_items_status",
        "journal_review_items",
        ["status"],
    )


def downgrade() -> None:
    """Drop journal_review_items table."""
    op.drop_index(
        "ix_journal_review_items_status",
        table_name="journal_review_items",
    )
    op.drop_index(
        "ix_journal_review_items_candidate_journal_id",
        table_name="journal_review_items",
    )
    op.drop_index(
        "ix_journal_review_items_source_journal_id",
        table_name="journal_review_items",
    )
    op.drop_table("journal_review_items")
