"""create journal external event links

Revision ID: 0028
Revises: 0027
Create Date: 2026-03-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "journal_external_event_links",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "calendar_id",
            sa.UUID(),
            sa.ForeignKey("calendars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_event_id", sa.VARCHAR(length=255), nullable=True),
        sa.Column("external_version", sa.VARCHAR(length=255), nullable=True),
        sa.Column("sync_capability", sa.VARCHAR(length=32), nullable=False),
        sa.Column("sync_status", sa.VARCHAR(length=32), nullable=False),
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
        sa.PrimaryKeyConstraint("journal_id", "calendar_id"),
        sa.CheckConstraint(
            "sync_capability IN ('outbound', 'bidirectional')",
            name="ck_journal_external_event_links_sync_capability",
        ),
        sa.CheckConstraint(
            "sync_status IN ('pending', 'synced', 'conflicted', 'cancelled', 'errored')",
            name="ck_journal_external_event_links_sync_status",
        ),
    )
    op.create_index(
        "ix_journal_external_event_links_calendar_lookup",
        "journal_external_event_links",
        ["calendar_id", "journal_id"],
    )
    op.execute(
        """
        INSERT INTO journal_external_event_links (
            journal_id,
            calendar_id,
            external_event_id,
            external_version,
            sync_capability,
            sync_status
        )
        SELECT
            journal_id,
            calendar_id,
            NULL,
            NULL,
            'outbound',
            'pending'
        FROM journal_calendar_info
        """
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(
        "ix_journal_external_event_links_calendar_lookup",
        table_name="journal_external_event_links",
    )
    op.drop_table("journal_external_event_links")
