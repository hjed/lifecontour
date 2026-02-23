"""Create journal_abseiling_data table for ABSEILING_TRIP type

Revision ID: 0021
Revises: 0020
Create Date: 2026-02-22 10:00:00.000000

This migration creates the journal_abseiling_data table for ITER4.5-004.

Type detection: A journal has the ABSEILING_TRIP type if a row exists in the
journal_abseiling_data table for that journal_id.

ABSEILING_TRIP requires OUTDOOR_ACTIVITY and FITNESS types. This is automatically
resolved by the service layer's type dependency system.

Note: Individual abseils are child journals with their own abseiling data.
This table tracks aggregate trip-level data (total count, combined length).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_abseiling_data table."""
    op.create_table(
        "journal_abseiling_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment="FK to journals - PK ensures one-to-one relationship",
        ),
        sa.Column(
            "number_of_abseils",
            sa.Integer(),
            nullable=True,
            comment="Total number of individual abseil pitches (non-negative)",
        ),
        sa.Column(
            "total_length",
            sa.Integer(),
            nullable=True,
            comment="Combined length of all abseils in metres (non-negative)",
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

    # number_of_abseils must be non-negative when provided
    op.create_check_constraint(
        "ck_abseiling_number_of_abseils_non_negative",
        "journal_abseiling_data",
        "number_of_abseils IS NULL OR number_of_abseils >= 0",
    )

    # total_length must be non-negative when provided
    op.create_check_constraint(
        "ck_abseiling_total_length_non_negative",
        "journal_abseiling_data",
        "total_length IS NULL OR total_length >= 0",
    )


def downgrade() -> None:
    """Drop journal_abseiling_data table."""
    op.drop_table("journal_abseiling_data")
