"""remove processed_at from outbox_events

Revision ID: 0053
Revises: 0052
Create Date: 2026-04-30 22:45:46.434781

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_column("outbox_events", "processed_at")


def downgrade() -> None:
    """Downgrade database schema."""
    op.add_column(
        "outbox_events",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
