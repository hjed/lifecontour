"""Add integration tables for sync metadata and external references

Revision ID: 0003
Revises: 0002
Create Date: 2024-06-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create integration tables for sync metadata and external references."""

    # Create sync_metadata table
    op.create_table(
        "sync_metadata",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("internal_id", sa.Integer(), nullable=False),
        sa.Column("integration_source", sa.VARCHAR(length=50), nullable=False),
        sa.Column("external_id", sa.VARCHAR(length=255), nullable=False),
        sa.Column(
            "last_synced_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column("version_hash", sa.VARCHAR(length=64), nullable=False),
        sa.Column("sync_status", sa.VARCHAR(length=20), nullable=False),
        sa.Column("error_message", sa.TEXT(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "sync_status IN ('success', 'failed', 'in_progress', 'pending')",
            name="ck_sync_metadata_sync_status",
        ),
        sa.CheckConstraint(
            "integration_source IN ('google_contacts', 'immich', 'strava', 'firefly_iii')",
            name="ck_sync_metadata_integration_source",
        ),
    )

    # Create external_references table
    op.create_table(
        "external_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.VARCHAR(length=50), nullable=False),
        sa.Column("integration_source", sa.VARCHAR(length=50), nullable=False),
        sa.Column("external_id", sa.VARCHAR(length=255), nullable=False),
        sa.Column("external_url", sa.TEXT(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "entity_type IN ('contact', 'journal_entry', 'calendar_event', 'photo', 'album', 'activity', 'transaction')",
            name="ck_external_references_entity_type",
        ),
        sa.CheckConstraint(
            "integration_source IN ('google_contacts', 'immich', 'strava', 'firefly_iii')",
            name="ck_external_references_integration_source",
        ),
    )

    # Create indexes for performance
    # Sync metadata indexes
    op.create_index("idx_sync_metadata_internal_id", "sync_metadata", ["internal_id"])
    op.create_index(
        "idx_sync_metadata_integration_external",
        "sync_metadata",
        ["integration_source", "external_id"],
        unique=True,
    )
    op.create_index("idx_sync_metadata_status", "sync_metadata", ["sync_status"])
    op.create_index(
        "idx_sync_metadata_last_synced", "sync_metadata", ["last_synced_at"]
    )
    op.create_index("idx_sync_metadata_retry_count", "sync_metadata", ["retry_count"])

    # External references indexes
    op.create_index(
        "idx_external_references_entity",
        "external_references",
        ["entity_id", "entity_type"],
    )
    op.create_index(
        "idx_external_references_integration_external",
        "external_references",
        ["integration_source", "external_id"],
        unique=True,
    )
    op.create_index(
        "idx_external_references_entity_type", "external_references", ["entity_type"]
    )


def downgrade() -> None:
    """Drop integration tables."""
    # Drop indexes first
    op.drop_index(
        "idx_external_references_entity_type", table_name="external_references"
    )
    op.drop_index(
        "idx_external_references_integration_external", table_name="external_references"
    )
    op.drop_index("idx_external_references_entity", table_name="external_references")

    op.drop_index("idx_sync_metadata_retry_count", table_name="sync_metadata")
    op.drop_index("idx_sync_metadata_last_synced", table_name="sync_metadata")
    op.drop_index("idx_sync_metadata_status", table_name="sync_metadata")
    op.drop_index("idx_sync_metadata_integration_external", table_name="sync_metadata")
    op.drop_index("idx_sync_metadata_internal_id", table_name="sync_metadata")

    # Drop tables
    op.drop_table("external_references")
    op.drop_table("sync_metadata")
