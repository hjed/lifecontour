"""add refresh_requested_at to contact_summaries

Revision ID: 0099
Revises: 0098
Create Date: 2026-07-16 20:02:43.168824

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0099"
down_revision: str | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the rolling-debounce marker for buffered summary refreshes.

    ``refresh_requested_at`` records the most recent automated
    ``ContactSummaryRefreshRequested`` event for the contact; the summary
    refresh sweeper dispatches generation once the contact has been quiet
    for the configured buffer window and clears the marker. NULL means no
    refresh is pending. The generator never writes this column, so an
    in-flight generation cannot clobber a newly arrived request.
    """
    op.add_column(
        "contact_summaries",
        sa.Column("refresh_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index keeps the sweeper's poll cheap: only rows with a pending
    # marker are indexed, and the table is mostly NULLs at rest.
    op.create_index(
        "ix_contact_summaries_refresh_requested_at",
        "contact_summaries",
        ["refresh_requested_at"],
        postgresql_where=sa.text("refresh_requested_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the refresh_requested_at marker column and its partial index."""
    op.drop_index(
        "ix_contact_summaries_refresh_requested_at",
        table_name="contact_summaries",
    )
    op.drop_column("contact_summaries", "refresh_requested_at")
