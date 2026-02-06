"""Create routes table for ITER4.5-001

Revision ID: 0016
Revises: 0015
Create Date: 2026-02-05 12:00:00.000000

This migration creates the routes table for reusable route/track names.
Routes are referenced by multiple activity types: BUSHWALKING, CANYONING,
CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING, and JOGGING.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create routes table."""
    # Create routes table
    op.create_table(
        "routes",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            comment="Unique identifier for the route",
        ),
        sa.Column(
            "user_id",
            sa.VARCHAR(length=50),
            nullable=False,
            comment="User who owns this route (FK to users when table exists)",
        ),
        sa.Column(
            "name",
            sa.VARCHAR(length=200),
            nullable=False,
            comment="Name of the route/track",
        ),
        sa.Column(
            "description",
            sa.TEXT(),
            nullable=True,
            comment="Optional description of the route",
        ),
        sa.Column(
            "gpx_data",
            sa.TEXT(),
            nullable=True,
            comment="GPX track data in XML format",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Last update timestamp",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance
    # Index on user_id for filtering routes by user
    op.create_index("idx_routes_user_id", "routes", ["user_id"])

    # Index on name for searching routes by name
    op.create_index("idx_routes_name", "routes", ["name"])

    # Index on created_at for sorting by creation date
    op.create_index("idx_routes_created_at", "routes", ["created_at"])


def downgrade() -> None:
    """Drop routes table and indexes."""
    # Drop indexes
    op.drop_index("idx_routes_created_at", table_name="routes")
    op.drop_index("idx_routes_name", table_name="routes")
    op.drop_index("idx_routes_user_id", table_name="routes")

    # Drop table
    op.drop_table("routes")
