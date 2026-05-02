"""add climbing template_id and kayaking white water fields

Revision ID: 0057
Revises: 0056
Create Date: 2026-05-02

CLIMBING changes:
  - Add template_id FK (UUID → activity_templates, nullable, SET NULL on delete)
  - Backfill journal_abseiling_data for existing climbing journals (new dependency)

KAYAKING changes:
  - Add is_white_water (boolean, nullable)
  - Add rapids_grade (text, nullable)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # --- CLIMBING: add template_id FK ---
    op.add_column(
        "journal_climbing_data",
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("activity_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- CLIMBING: backfill abseiling data for existing climbing journals ---
    # CLIMBING now depends on ABSEILING_TRIP, so every climbing journal
    # must have a corresponding journal_abseiling_data row.
    op.execute(
        """
        INSERT INTO journal_abseiling_data (journal_id, created_at, updated_at)
        SELECT c.journal_id, NOW(), NOW()
        FROM journal_climbing_data c
        LEFT JOIN journal_abseiling_data a ON c.journal_id = a.journal_id
        WHERE a.journal_id IS NULL
        """
    )

    # --- KAYAKING: add white water fields ---
    op.add_column(
        "journal_kayaking_data",
        sa.Column("is_white_water", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "journal_kayaking_data",
        sa.Column("rapids_grade", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # --- KAYAKING: remove white water fields ---
    op.drop_column("journal_kayaking_data", "rapids_grade")
    op.drop_column("journal_kayaking_data", "is_white_water")

    # --- CLIMBING: remove backfilled abseiling data ---
    # Note: Downgrade is non-destructive for journal_abseiling_data.
    # We intentionally do not delete backfilled rows, as deleting rows where all fields
    # are NULL could also unintentionally delete legitimately-created ABSEILING_TRIP
    # rows that have no aggregate values entered yet.

    # --- CLIMBING: remove template_id column ---
    op.drop_column("journal_climbing_data", "template_id")
