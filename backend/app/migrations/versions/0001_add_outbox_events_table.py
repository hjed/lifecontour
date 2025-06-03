"""Add outbox_events table for transactional outbox pattern

Revision ID: 0001
Revises:
Create Date: 2024-06-01 23:05:00.000000

"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create outbox_events table for transactional outbox pattern."""
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=False),
        sa.Column("event_data", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(), nullable=False, default=datetime.utcnow
        ),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False, default=datetime.utcnow),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance
    op.create_index(
        "ix_outbox_events_event_id", "outbox_events", ["event_id"], unique=True
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_processed_at", "outbox_events", ["processed_at"])


def downgrade() -> None:
    """Drop outbox_events table."""
    op.drop_index("ix_outbox_events_processed_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_aggregate_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_id", table_name="outbox_events")
    op.drop_table("outbox_events")
