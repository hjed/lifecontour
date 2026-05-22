"""add snipeit_checkout to integration_source check constraint

Revision ID: 0077
Revises: 0076
Create Date: 2026-05-22 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout')",
    )


def downgrade() -> None:
    # Remove any snipeit_checkout rows before reverting the constraint
    op.execute(
        "DELETE FROM sync_metadata WHERE integration_source = 'snipeit_checkout'"
    )

    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii', 'snipeit', 'snipeit_maintenance')",
    )
