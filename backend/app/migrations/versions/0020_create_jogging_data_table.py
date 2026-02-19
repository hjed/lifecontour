"""Create journal_jogging_data table for JOGGING type

Revision ID: 0020
Revises: 0019
Create Date: 2026-02-18 12:02:00.000000

This migration creates the journal_jogging_data table for ITER4.5-003.

Type detection: A journal has the JOGGING type if a row exists in the
journal_jogging_data table for that journal_id.

JOGGING requires the FITNESS type only (NOT OUTDOOR_ACTIVITY - jogging can take
place on treadmills or indoor tracks). This is automatically resolved by the
service layer's type dependency system.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_jogging_data table."""
    op.create_table(
        "journal_jogging_data",
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
            "pace",
            sa.Integer(),
            nullable=True,
            comment="Pace in seconds per kilometre (non-negative)",
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

    # Pace must be non-negative when provided
    op.create_check_constraint(
        "ck_jogging_pace_non_negative",
        "journal_jogging_data",
        "pace IS NULL OR pace >= 0",
    )


def downgrade() -> None:
    """Drop journal_jogging_data table."""
    op.drop_table("journal_jogging_data")
