"""Create journal_canyoning_data table for CANYONING type

Revision ID: 0022
Revises: 0021
Create Date: 2026-02-22 10:01:00.000000

This migration creates the journal_canyoning_data table for ITER4.5-004.

Type detection: A journal has the CANYONING type if a row exists in the
journal_canyoning_data table for that journal_id.

CANYONING requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, and FITNESS types.
This is automatically resolved by the service layer's type dependency system.

French Canyon Grading System (stored in french_grade field):
  Format: v[vertical]a[aquatic][engagement][stars]
  Example: v3a2IV** = vertical 3, aquatic 2, engagement IV, 2 stars
  Vertical/Aquatic: 1-7, Engagement: I-VI (optional), Stars: *-*** (optional)

Note: water_guage_name is intentionally spelled with the 'u' (matches spec).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_canyoning_data table."""
    op.create_table(
        "journal_canyoning_data",
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
            "french_grade",
            sa.String(20),
            nullable=True,
            comment="French canyon grade e.g. 'v3a2IV**'",
        ),
        sa.Column(
            "water_guage_name",
            sa.String(200),
            nullable=True,
            comment="Name of water gauge used for flow measurement",
        ),
        sa.Column(
            "water_guage_level",
            sa.Integer(),
            nullable=True,
            comment="Water gauge reading at time of trip",
        ),
        sa.Column(
            "is_vertical",
            sa.Boolean(),
            nullable=True,
            comment="Whether canyon is primarily vertical",
        ),
        sa.Column(
            "is_night_canyon",
            sa.Boolean(),
            nullable=True,
            comment="Whether trip was done at night",
        ),
        sa.Column(
            "is_white_water",
            sa.Boolean(),
            nullable=True,
            comment="Whether canyon has significant white water",
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
    """Drop journal_canyoning_data table."""
    op.drop_table("journal_canyoning_data")
