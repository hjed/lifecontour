"""Create journal_climbing_data table for CLIMBING type

Revision ID: 0023
Revises: 0022
Create Date: 2026-02-22 10:02:00.000000

This migration creates the journal_climbing_data table for ITER4.5-004.

Type detection: A journal has the CLIMBING type if a row exists in the
journal_climbing_data table for that journal_id.

CLIMBING requires OUTDOOR_ACTIVITY and FITNESS types. This is automatically
resolved by the service layer's type dependency system.

Climbing types: "sport", "trad", "bouldering"
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_climbing_data table."""
    op.create_table(
        "journal_climbing_data",
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
            "climbing_type",
            sa.String(20),
            nullable=True,
            comment="Climbing discipline: sport, trad, or bouldering",
        ),
        sa.Column(
            "grade",
            sa.Integer(),
            nullable=True,
            comment="Numeric climbing grade (non-negative)",
        ),
        sa.Column(
            "length",
            sa.Integer(),
            nullable=True,
            comment="Route length in metres (non-negative)",
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

    # grade must be non-negative when provided
    op.create_check_constraint(
        "ck_climbing_grade_non_negative",
        "journal_climbing_data",
        "grade IS NULL OR grade >= 0",
    )

    # length must be non-negative when provided
    op.create_check_constraint(
        "ck_climbing_length_non_negative",
        "journal_climbing_data",
        "length IS NULL OR length >= 0",
    )

    # climbing_type must be one of the valid values when provided
    op.create_check_constraint(
        "ck_climbing_type_valid",
        "journal_climbing_data",
        "climbing_type IS NULL OR climbing_type IN ('sport', 'trad', 'bouldering')",
    )


def downgrade() -> None:
    """Drop journal_climbing_data table."""
    op.drop_table("journal_climbing_data")
