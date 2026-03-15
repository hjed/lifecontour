"""Add syncing to ExternalEventLinkSyncStatus

Revision ID: 0032
Revises: 0031
Create Date: 2026-03-15 17:33:20.198886

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_constraint(
        "ck_journal_external_event_links_sync_status",
        "journal_external_event_links",
        type_="check",
    )
    op.create_check_constraint(
        "ck_journal_external_event_links_sync_status",
        "journal_external_event_links",
        "sync_status IN ('pending', 'syncing', 'synced', 'conflicted', 'cancelled', 'errored')",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint(
        "ck_journal_external_event_links_sync_status",
        "journal_external_event_links",
        type_="check",
    )
    op.create_check_constraint(
        "ck_journal_external_event_links_sync_status",
        "journal_external_event_links",
        "sync_status IN ('pending', 'synced', 'conflicted', 'cancelled', 'errored')",
    )
