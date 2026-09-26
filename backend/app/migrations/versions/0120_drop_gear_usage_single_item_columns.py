"""drop gear usage single item columns

Revision ID: 0120
Revises: 0119
Create Date: 2026-09-27 12:00:00.000000

A GEAR_USAGE entry's gear items live in ``journal_gear_usage_items`` (0119, #1574).
Every reader has moved there, so the entry's own ``gear_item_id`` /
``checkout_date`` / ``checkin_date`` — kept as a mirror of its first item while
they moved — are dropped. The entry row stays: it is what gives a journal the
GEAR_USAGE type.

Downgrading re-adds them and refills each from the entry's first item.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0120"
down_revision: str | None = "0119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "journal_gear_usage_data"
_INDEX = "ix_journal_gear_usage_data_gear_item_id"
_FK = "journal_gear_usage_data_gear_item_id_fkey"


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "gear_item_id")
    op.drop_column(_TABLE, "checkout_date")
    op.drop_column(_TABLE, "checkin_date")


def downgrade() -> None:
    """Downgrade database schema."""
    op.add_column(_TABLE, sa.Column("gear_item_id", sa.UUID(), nullable=True))
    op.add_column(
        _TABLE, sa.Column("checkout_date", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        _TABLE, sa.Column("checkin_date", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        _FK, _TABLE, "gear_items", ["gear_item_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(_INDEX, _TABLE, ["gear_item_id"])
    op.execute(
        """
        UPDATE journal_gear_usage_data d
        SET gear_item_id = i.gear_item_id,
            checkout_date = i.checkout_date,
            checkin_date = i.checkin_date
        FROM (
            SELECT DISTINCT ON (journal_id)
                   journal_id, gear_item_id, checkout_date, checkin_date
            FROM journal_gear_usage_items
            ORDER BY journal_id, position, gear_item_id
        ) i
        WHERE i.journal_id = d.journal_id
        """
    )
