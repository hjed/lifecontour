"""Add sync_jobs table for tracking sync job history

Revision ID: 0013
Revises: 0012
Create Date: 2025-01-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add sync_jobs table for persisting sync job history."""
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "job_id",
            sa.String(length=255),
            nullable=False,
            unique=True,
            comment="ARQ job ID for tracking in Redis",
        ),
        sa.Column(
            "user_id",
            sa.String(length=50),
            nullable=False,
            comment="User who initiated the sync",
        ),
        sa.Column(
            "integration_source",
            sa.String(length=50),
            nullable=False,
            comment="Integration source (e.g., 'google_contacts')",
        ),
        sa.Column(
            "sync_type",
            sa.String(length=20),
            nullable=False,
            comment="Type of sync: 'smart', 'full'",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            comment="Job status: 'queued', 'running', 'completed', 'failed', 'cancelled'",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="When the job was created",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the job started processing",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the job completed",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Error message if job failed",
        ),
        sa.Column(
            "contacts_processed",
            sa.Integer(),
            nullable=True,
            comment="Number of contacts processed",
        ),
        sa.Column(
            "contacts_created",
            sa.Integer(),
            nullable=True,
            comment="Number of contacts created",
        ),
        sa.Column(
            "contacts_updated",
            sa.Integer(),
            nullable=True,
            comment="Number of contacts updated",
        ),
        sa.Column(
            "contacts_deleted",
            sa.Integer(),
            nullable=True,
            comment="Number of contacts deleted",
        ),
        sa.Column(
            "progress",
            sa.Integer(),
            nullable=True,
            comment="Progress percentage (0-100)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Last update timestamp",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_sync_jobs_status",
        ),
        sa.CheckConstraint(
            "sync_type IN ('smart', 'full')",
            name="ck_sync_jobs_sync_type",
        ),
        sa.CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
            name="ck_sync_jobs_progress_range",
        ),
    )

    # Create indexes for efficient querying
    op.create_index(
        op.f("ix_sync_jobs_job_id"),
        "sync_jobs",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_sync_jobs_user_id"),
        "sync_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sync_jobs_status"),
        "sync_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sync_jobs_created_at"),
        "sync_jobs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove sync_jobs table."""
    op.drop_index(op.f("ix_sync_jobs_created_at"), table_name="sync_jobs")
    op.drop_index(op.f("ix_sync_jobs_status"), table_name="sync_jobs")
    op.drop_index(op.f("ix_sync_jobs_user_id"), table_name="sync_jobs")
    op.drop_index(op.f("ix_sync_jobs_job_id"), table_name="sync_jobs")
    op.drop_table("sync_jobs")
