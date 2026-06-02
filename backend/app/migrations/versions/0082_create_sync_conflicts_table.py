"""Create sync_conflicts table

Revision ID: 0082
Revises: 0081
Create Date: 2026-06-02 19:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create sync_conflicts table for unresolved integration sync conflicts."""
    op.create_table(
        "sync_conflicts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=50),
            nullable=False,
            comment="User ID who owns this conflict",
        ),
        sa.Column(
            "integration_source",
            sa.String(length=50),
            nullable=False,
            comment="Integration source (e.g., 'immich')",
        ),
        sa.Column(
            "external_entity_id",
            sa.String(length=255),
            nullable=False,
            comment="External system's entity ID (e.g., Immich person UUID)",
        ),
        sa.Column(
            "external_entity_name",
            sa.String(length=255),
            nullable=True,
            comment="Display name of the external entity",
        ),
        sa.Column(
            "candidate_contact_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
            comment="JSON array of candidate contact IDs",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="unresolved",
            comment="Conflict status: 'unresolved' or 'resolved'",
        ),
        sa.Column(
            "resolved_contact_id",
            sa.Integer(),
            nullable=True,
            comment="Contact ID chosen for resolution (null if unresolved)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('unresolved', 'resolved')",
            name="ck_sync_conflicts_status",
        ),
    )
    # Partial unique index: only one unresolved conflict per user+source+entity
    op.create_index(
        "uq_sync_conflicts_active",
        "sync_conflicts",
        ["user_id", "integration_source", "external_entity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'unresolved'"),
    )
    # Index for listing conflicts by user
    op.create_index(
        "ix_sync_conflicts_user_status",
        "sync_conflicts",
        ["user_id", "integration_source", "status"],
    )


def downgrade() -> None:
    """Remove sync_conflicts table."""
    op.drop_index("ix_sync_conflicts_user_status", table_name="sync_conflicts")
    op.drop_index("uq_sync_conflicts_active", table_name="sync_conflicts")
    op.drop_table("sync_conflicts")
