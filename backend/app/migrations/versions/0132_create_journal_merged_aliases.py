"""create journal_merged_aliases

Revision ID: 0132
Revises: 0131
Create Date: 2026-10-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0132"
down_revision: str | None = "0131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep the inbound records a merge absorbed recognisable.

    A merge deletes the source journal, and any external link the target could
    not take over went with it: a second event in a calendar the target is
    already linked in (links are one per journal per calendar), a rival
    Strava activity or Immich album in a replace merge. The next sync then saw
    a record it had never journalled and imported it again.

    A row here says "this record is that journal". It is recognition only:
    nothing pushes to it, and it is a table of its own so no outbound path,
    which reads links, can reach it.
    """
    op.create_table(
        "journal_merged_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("integration_source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=True),
        sa.Column("external_identity", sa.String(length=512), nullable=True),
        sa.Column("recurring_event_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["calendar_id"], ["calendars.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "user_id",
            "integration_source",
            "external_id",
            name="uq_journal_merged_aliases_user_source_external",
        ),
    )
    op.create_index(
        "ix_journal_merged_aliases_journal",
        "journal_merged_aliases",
        ["journal_id"],
    )
    op.create_index(
        "ix_journal_merged_aliases_identity",
        "journal_merged_aliases",
        ["user_id", "external_identity"],
        postgresql_where=sa.text("external_identity IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop journal_merged_aliases."""
    op.drop_index(
        "ix_journal_merged_aliases_identity", table_name="journal_merged_aliases"
    )
    op.drop_index(
        "ix_journal_merged_aliases_journal", table_name="journal_merged_aliases"
    )
    op.drop_table("journal_merged_aliases")
