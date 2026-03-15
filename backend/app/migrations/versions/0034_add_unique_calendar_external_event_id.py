"""add unique constraint on (calendar_id, external_event_id)

Revision ID: 0034
Revises: 0033
Create Date: 2026-03-15 21:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add unique partial index on (calendar_id, external_event_id).

    Ensures deterministic lookups by external_event_id within a calendar.
    Uses a partial index to allow multiple NULL external_event_id values
    (outbound-only links that don't yet have an external ID).
    """
    op.create_index(
        "uq_journal_external_event_links_cal_ext_event",
        "journal_external_event_links",
        ["calendar_id", "external_event_id"],
        unique=True,
        postgresql_where="external_event_id IS NOT NULL",
    )


def downgrade() -> None:
    """Remove unique partial index."""
    op.drop_index(
        "uq_journal_external_event_links_cal_ext_event",
        table_name="journal_external_event_links",
    )
