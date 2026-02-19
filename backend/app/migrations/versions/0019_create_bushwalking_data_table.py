"""Create journal_bushwalking_data table for BUSHWALKING type

Revision ID: 0019
Revises: 0018
Create Date: 2026-02-18 12:01:00.000000

This migration creates the journal_bushwalking_data table for ITER4.5-003.

Type detection: A journal has the BUSHWALKING type if a row exists in the
journal_bushwalking_data table for that journal_id.

BUSHWALKING requires OUTDOOR_ACTIVITY and FITNESS types (automatically resolved
by the service layer's type dependency system).

Australian Track Grading System:
  Grade 1: Well-formed track, suitable for wheelchairs
  Grade 2: Well-formed track, suitable for most ages and fitness levels
  Grade 3: Formed track, some steep sections
  Grade 4: Rough track, very steep sections
  Grade 5: Route only, very rough and very steep
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_bushwalking_data table."""
    op.create_table(
        "journal_bushwalking_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment="FK to journals - PK ensures one-to-one relationship",
        ),
        sa.Column(
            "route_id",
            sa.UUID(),
            sa.ForeignKey("routes.id", ondelete="SET NULL"),
            nullable=True,
            comment="Optional FK to routes table",
        ),
        sa.Column(
            "track_grading",
            sa.VARCHAR(length=10),
            nullable=True,
            comment="Australian Track Grading System grade (Grade 1-5)",
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
        sa.PrimaryKeyConstraint("journal_id"),
    )

    # Enforce Australian Track Grading System values
    op.create_check_constraint(
        "ck_bushwalking_track_grading_valid",
        "journal_bushwalking_data",
        "track_grading IS NULL OR track_grading IN "
        "('Grade 1', 'Grade 2', 'Grade 3', 'Grade 4', 'Grade 5')",
    )


def downgrade() -> None:
    """Drop journal_bushwalking_data table."""
    op.drop_table("journal_bushwalking_data")
