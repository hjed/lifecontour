"""consolidate template_id to abseiling_data

Revision ID: 0094
Revises: 0093
Create Date: 2026-06-30

ITER16-001 Phase 1 — Durable Template Reference on Abseiling Activities.

Additive data-layer change:
  - Add ``ck_activity_templates_type`` support for the new ``abseiling`` template
    type (drop + recreate the CHECK constraint).
  - Add a nullable ``template_id`` UUID FK to ``journal_abseiling_data``
    (``ON DELETE SET NULL``), co-locating the template reference with the abseil
    pitch data it populated.
  - Backfill it from the existing per-subtype ``template_id`` columns on
    ``journal_canyoning_data`` / ``journal_climbing_data`` / ``journal_caving_data``
    (each abseiling-derived journal already has a ``journal_abseiling_data`` row).

The old per-subtype columns are left in place — both coexist until ITER16-001
Phase 5 retires them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0094"
down_revision: str | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # --- activity_templates: allow the new 'abseiling' template type ---
    op.drop_constraint("ck_activity_templates_type", "activity_templates")
    op.create_check_constraint(
        "ck_activity_templates_type",
        "activity_templates",
        "template_type IN ('abseiling', 'canyoning', 'caving', 'climbing')",
    )

    # --- journal_abseiling_data: add consolidated template_id FK ---
    op.add_column(
        "journal_abseiling_data",
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("activity_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- Backfill from the existing per-subtype template_id columns ---
    # Each abseiling-derived journal already has a journal_abseiling_data row.
    # Precedence (canyoning > climbing > caving) is only relevant for the
    # degenerate case of a journal carrying more than one subtype reference.
    op.execute(
        """
        UPDATE journal_abseiling_data AS a
        SET template_id = COALESCE(can.template_id, cli.template_id, cav.template_id)
        FROM journal_abseiling_data AS base
        LEFT JOIN journal_canyoning_data AS can ON can.journal_id = base.journal_id
        LEFT JOIN journal_climbing_data AS cli ON cli.journal_id = base.journal_id
        LEFT JOIN journal_caving_data AS cav ON cav.journal_id = base.journal_id
        WHERE a.journal_id = base.journal_id
          AND COALESCE(can.template_id, cli.template_id, cav.template_id) IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade database schema.

    Non-destructive for the per-subtype columns: they retain their values, so
    dropping the consolidated column loses no source data.
    """
    op.drop_column("journal_abseiling_data", "template_id")

    op.drop_constraint("ck_activity_templates_type", "activity_templates")
    op.create_check_constraint(
        "ck_activity_templates_type",
        "activity_templates",
        "template_type IN ('canyoning', 'caving', 'climbing')",
    )
