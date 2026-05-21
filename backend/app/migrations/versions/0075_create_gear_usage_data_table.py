"""create gear usage data table

Revision ID: 0075
Revises: 0074
Create Date: 2026-05-20 13:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journal_gear_usage_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "gear_item_id",
            sa.UUID(),
            sa.ForeignKey("gear_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("checkout_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkin_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_journal_gear_usage_data_gear_item_id",
        "journal_gear_usage_data",
        ["gear_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_journal_gear_usage_data_gear_item_id", table_name="journal_gear_usage_data"
    )
    op.drop_table("journal_gear_usage_data")
