"""Create journal_kayaking_data and journal_skiing_data tables for ITER4.5-005

Revision ID: 0024
Revises: 0023
Create Date: 2026-02-23 10:00:00.000000

This migration creates the data tables for KAYAKING and CROSS_COUNTRY_SKIING
journal types.

KAYAKING type detection: A journal has the KAYAKING type if a row exists in
journal_kayaking_data for that journal_id.

CROSS_COUNTRY_SKIING type detection: A journal has the CROSS_COUNTRY_SKIING type
if a row exists in journal_skiing_data for that journal_id.

KAYAKING requires OUTDOOR_ACTIVITY and FITNESS types.
CROSS_COUNTRY_SKIING requires BUSHWALKING, OUTDOOR_ACTIVITY, and FITNESS types.
Both are automatically resolved by the service layer's type dependency system.

water_type examples: "river", "sea", "lake" (open-ended text field)
snow_conditions: free-form text description
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_kayaking_data and journal_skiing_data tables."""
    op.create_table(
        "journal_kayaking_data",
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
            comment="Optional FK to routes table (waterway reference)",
        ),
        sa.Column(
            "water_type",
            sa.Text(),
            nullable=True,
            comment="Type of water body (e.g., river, sea, lake)",
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

    op.create_table(
        "journal_skiing_data",
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
            comment="Optional FK to routes table (ski trail reference)",
        ),
        sa.Column(
            "snow_conditions",
            sa.Text(),
            nullable=True,
            comment="Description of snow conditions",
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


def downgrade() -> None:
    """Drop journal_kayaking_data and journal_skiing_data tables."""
    op.drop_table("journal_skiing_data")
    op.drop_table("journal_kayaking_data")
