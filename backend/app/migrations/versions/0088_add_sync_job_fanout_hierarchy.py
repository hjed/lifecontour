"""Add sync_jobs fan-out hierarchy columns and in_progress status

Revision ID: 0088
Revises: 0087
Create Date: 2026-06-16 00:00:00.000000

Non-blocking fan-outs: adds an ``in_progress`` status for orchestrator (parent)
jobs whose children have been dispatched but not yet finalised, plus parent/child
tracking on ``sync_jobs``:

- ``parent_job_id`` — self-referencing link from a child batch job to its
  orchestrator (null for top-level jobs).
- ``expected_children`` / ``completed_children`` / ``failed_children`` — child
  counters on the parent (default 0; existing rows backfill to 0).

The ``ck_sync_jobs_status`` check constraint is extended to allow ``in_progress``;
all other statuses are unchanged. Additive only — no orchestrator yet emits the
new status, so this merges green.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_WITH_IN_PROGRESS = (
    "status IN ('queued', 'running', 'in_progress', 'completed', 'failed', 'cancelled')"
)
_STATUS_WITHOUT_IN_PROGRESS = (
    "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')"
)


def upgrade() -> None:
    """Add the fan-out hierarchy columns and extend the status constraint."""
    op.add_column(
        "sync_jobs",
        sa.Column(
            "parent_job_id",
            sa.String(length=255),
            nullable=True,
            comment=(
                "Parent orchestrator job_id for a child batch job (null if top-level)"
            ),
        ),
    )
    op.add_column(
        "sync_jobs",
        sa.Column(
            "expected_children",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Number of child jobs dispatched by this orchestrator",
        ),
    )
    op.add_column(
        "sync_jobs",
        sa.Column(
            "completed_children",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Number of child jobs that have completed successfully",
        ),
    )
    op.add_column(
        "sync_jobs",
        sa.Column(
            "failed_children",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Number of child jobs that have failed",
        ),
    )

    op.create_index(
        "ix_sync_jobs_parent_job_id",
        "sync_jobs",
        ["parent_job_id"],
    )
    op.create_foreign_key(
        "fk_sync_jobs_parent_job_id",
        "sync_jobs",
        "sync_jobs",
        ["parent_job_id"],
        ["job_id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("ck_sync_jobs_status", "sync_jobs", type_="check")
    op.create_check_constraint(
        "ck_sync_jobs_status",
        "sync_jobs",
        _STATUS_WITH_IN_PROGRESS,
    )


def downgrade() -> None:
    """Reverse the fan-out hierarchy columns and status constraint extension."""
    # Demote any in_progress rows before tightening the constraint.
    op.execute("UPDATE sync_jobs SET status = 'failed' WHERE status = 'in_progress'")

    op.drop_constraint("ck_sync_jobs_status", "sync_jobs", type_="check")
    op.create_check_constraint(
        "ck_sync_jobs_status",
        "sync_jobs",
        _STATUS_WITHOUT_IN_PROGRESS,
    )

    op.drop_constraint("fk_sync_jobs_parent_job_id", "sync_jobs", type_="foreignkey")
    op.drop_index("ix_sync_jobs_parent_job_id", table_name="sync_jobs")
    op.drop_column("sync_jobs", "failed_children")
    op.drop_column("sync_jobs", "completed_children")
    op.drop_column("sync_jobs", "expected_children")
    op.drop_column("sync_jobs", "parent_job_id")
