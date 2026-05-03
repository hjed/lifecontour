"""Add 'conflict' to sync_metadata sync_status CHECK constraint

Revision ID: 0052
Revises: 0051
Create Date: 2026-04-30 08:47:59.580642

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'conflict' status to sync_metadata CHECK constraint."""
    op.drop_constraint("ck_sync_metadata_sync_status", "sync_metadata", type_="check")
    op.create_check_constraint(
        "ck_sync_metadata_sync_status",
        "sync_metadata",
        "sync_status IN ('success', 'failed', 'in_progress', 'pending', 'conflict')",
    )


def downgrade() -> None:
    """Remove 'conflict' status from sync_metadata CHECK constraint."""
    op.drop_constraint("ck_sync_metadata_sync_status", "sync_metadata", type_="check")
    op.create_check_constraint(
        "ck_sync_metadata_sync_status",
        "sync_metadata",
        "sync_status IN ('success', 'failed', 'in_progress', 'pending')",
    )
