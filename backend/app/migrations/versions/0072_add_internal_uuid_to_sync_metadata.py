"""add internal_uuid to sync_metadata

Revision ID: 0072
Revises: 0071
Create Date: 2026-05-17 09:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Make internal_id nullable and add internal_uuid
    op.alter_column(
        "sync_metadata", "internal_id", existing_type=sa.INTEGER(), nullable=True
    )
    op.add_column(
        "sync_metadata", sa.Column("internal_uuid", sa.String(length=36), nullable=True)
    )

    # Update check constraints for 'snipeit' integration source
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii', 'snipeit')",
    )


def downgrade() -> None:
    # Delete rows that use internal_uuid (Snipe-IT) or lack an internal_id
    # to allow internal_id to safely become NOT NULL again.
    op.execute("DELETE FROM sync_metadata WHERE internal_id IS NULL")

    # Revert check constraints
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii')",
    )

    # Revert changes
    op.drop_column("sync_metadata", "internal_uuid")
    op.alter_column(
        "sync_metadata", "internal_id", existing_type=sa.INTEGER(), nullable=False
    )
