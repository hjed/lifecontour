"""add external_identity to journal_external_event_links

Revision ID: 0108
Revises: 0107
Create Date: 2026-08-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the integration's cross-calendar identity for an event.

    ``external_event_id`` identifies an event only *within* one calendar, so
    the same real-world event present in two calendars — one calendar having
    invited the other — looks like two unrelated events and produces two
    journals.

    This column carries an **opaque token, supplied by the integration
    worker**, that is equal for every copy of the same real-world event. What
    goes into it is the worker's business; the only rule this side of the
    outbox is that two links sharing a token for the same user describe the
    same thing and therefore belong to the same journal.

    Nullable: links predating this column carry no token until their next
    sync backfills one, and integrations with no cross-source identity of
    their own simply never set it.
    """
    op.add_column(
        "journal_external_event_links",
        sa.Column("external_identity", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_journal_external_event_links_identity",
        "journal_external_event_links",
        ["external_identity"],
        postgresql_where=sa.text("external_identity IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the external_identity column and its index."""
    op.drop_index(
        "ix_journal_external_event_links_identity",
        table_name="journal_external_event_links",
    )
    op.drop_column("journal_external_event_links", "external_identity")
