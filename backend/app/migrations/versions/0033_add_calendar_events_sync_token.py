"""add calendar_events_sync_token to user_google_integration

Revision ID: 0033
Revises: 0032
Create Date: 2026-03-15 18:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add calendar_events_sync_token column for incremental calendar sync."""
    op.add_column(
        "user_google_integration",
        sa.Column(
            "calendar_events_sync_token",
            sa.String(length=500),
            nullable=True,
            comment="Google Calendar Events sync token for incremental sync",
        ),
    )


def downgrade() -> None:
    """Remove calendar_events_sync_token column."""
    op.drop_column("user_google_integration", "calendar_events_sync_token")
