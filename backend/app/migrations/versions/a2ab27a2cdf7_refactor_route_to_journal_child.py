"""refactor_route_to_journal_child

Revision ID: a2ab27a2cdf7
Revises: 0028
Create Date: 2026-03-13 22:32:45.919712

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2ab27a2cdf7"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # 1. Routes table: add journal_id, delete routes, alter to NOT NULL, drop user_id
    op.add_column("routes", sa.Column("journal_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_routes_journal_id",
        "routes",
        "journals",
        ["journal_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Clear existing routes to maintain data integrity before making it NOT NULL
    op.execute("DELETE FROM routes")
    op.alter_column("routes", "journal_id", nullable=False)
    op.drop_column("routes", "user_id")

    # 2. Activity data tables: drop route_id
    activity_tables = [
        "journal_bushwalking_data",
        "journal_canyoning_data",
        "journal_climbing_data",
        "journal_skiing_data",
        "journal_jogging_data",
        "journal_kayaking_data",
    ]
    for table in activity_tables:
        op.drop_column(table, "route_id")

    # 3. Fitness data: drop gpx_track_data
    op.drop_column("journal_fitness_data", "gpx_track_data")


def downgrade() -> None:
    """Downgrade database schema."""
    # Fitness data: add gpx_track_data
    op.add_column(
        "journal_fitness_data", sa.Column("gpx_track_data", sa.Text(), nullable=True)
    )

    # Activity data tables: add route_id
    activity_tables = [
        "journal_bushwalking_data",
        "journal_canyoning_data",
        "journal_climbing_data",
        "journal_skiing_data",
        "journal_jogging_data",
        "journal_kayaking_data",
    ]
    for table in activity_tables:
        op.add_column(
            table,
            sa.Column(
                "route_id",
                sa.UUID(),
                sa.ForeignKey("routes.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # Routes table: reverse changes
    op.add_column("routes", sa.Column("user_id", sa.VARCHAR(length=50), nullable=True))
    op.execute("DELETE FROM routes")
    op.alter_column("routes", "user_id", nullable=False)
    op.drop_constraint("fk_routes_journal_id", "routes", type_="foreignkey")
    op.drop_column("routes", "journal_id")
