"""refactor route to journal child

Revision ID: 0031
Revises: 0030
Create Date: 2026-03-13 22:32:45.919712

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0031"
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
    # To preserve existing routes instead of deleting them, we create a
    # placeholder journal to attach orphaned routes to per user before making journal_id NOT NULL.
    op.execute(
        """
        INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end, "order", created_at, updated_at)
        SELECT DISTINCT user_id, 'Archived Routes', '', CURRENT_DATE, CURRENT_DATE, 0, clock_timestamp(), clock_timestamp()
        FROM routes
        WHERE journal_id IS NULL AND user_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE routes
        SET journal_id = (
            SELECT id FROM journals
            WHERE title = 'Archived Routes' AND journals.user_id = routes.user_id
            LIMIT 1
        )
        WHERE journal_id IS NULL AND user_id IS NOT NULL
        """
    )
    # If there are any routes with both journal_id AND user_id as NULL, we have no secure way to keep them
    op.execute("DELETE FROM routes WHERE journal_id IS NULL")
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
