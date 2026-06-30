"""add snipeit_checkin to integration_source check constraint

Revision ID: 0094
Revises: 0093
Create Date: 2026-06-30 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0094"
down_revision: str | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout', 'snipeit_checkin')",
    )


def downgrade() -> None:
    # Remove any snipeit_checkin rows before reverting the constraint
    op.execute("DELETE FROM sync_metadata WHERE integration_source = 'snipeit_checkin'")

    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout')",
    )
