"""Add sync_jobs listing cursor columns

Revision ID: 0125
Revises: 0124
Create Date: 2026-10-07 00:00:00.000000

A smart sync fetches only the records changed since the last successful run.
The orchestrator records, on its parent row, which resource it listed
(``sync_resource``) and the newest change it saw (``sync_cursor``, in the
integration's own clock). The next smart run reads the cursor of the newest
parent that completed, so a run that failed never moves it.

Additive only: existing rows have neither, so their next smart run is a full one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0125"
down_revision: str | None = "0124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the listing cursor columns."""
    op.add_column(
        "sync_jobs",
        sa.Column(
            "sync_resource",
            sa.String(length=50),
            nullable=True,
            comment="Resource an orchestrator listed (e.g. 'assets'), null if none",
        ),
    )
    op.add_column(
        "sync_jobs",
        sa.Column(
            "sync_cursor",
            sa.String(length=64),
            nullable=True,
            comment="Newest change the listing saw, in the integration's own clock",
        ),
    )


def downgrade() -> None:
    """Drop the listing cursor columns."""
    op.drop_column("sync_jobs", "sync_cursor")
    op.drop_column("sync_jobs", "sync_resource")
