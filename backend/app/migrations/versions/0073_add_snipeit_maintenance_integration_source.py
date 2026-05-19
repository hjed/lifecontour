"""add snipeit_maintenance to integration_source check constraint

Revision ID: 0073
Revises: 0072
Create Date: 2026-05-18 23:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii', 'snipeit', 'snipeit_maintenance')",
    )


def downgrade() -> None:
    # Remove any snipeit_maintenance rows before reverting the constraint
    op.execute(
        "DELETE FROM sync_metadata WHERE integration_source = 'snipeit_maintenance'"
    )

    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii', 'snipeit')",
    )
