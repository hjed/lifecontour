"""add snipeit_maintenance_claim to integration_source check constraint

Revision ID: 0113
Revises: 0112
Create Date: 2026-09-16 12:00:00.000000

A Snipe-IT maintenance push writes a claim row before posting the record, so a
push that fails after the POST leaves the record's title and date for its retry
to find. Claims get their own source so journal link readers never show one.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0113"
down_revision: str | None = "0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'immich_album', 'strava', 'firefly_iii', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout', 'snipeit_checkin', 'snipeit_maintenance_claim')",
    )


def downgrade() -> None:
    # Remove any snipeit_maintenance_claim rows before reverting the constraint
    op.execute(
        "DELETE FROM sync_metadata WHERE integration_source = 'snipeit_maintenance_claim'"
    )

    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'immich_album', 'strava', 'firefly_iii', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout', 'snipeit_checkin')",
    )
