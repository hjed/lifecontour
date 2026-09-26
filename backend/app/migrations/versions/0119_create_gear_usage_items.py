"""create gear usage items

Revision ID: 0119
Revises: 0118
Create Date: 2026-09-26 15:00:00.000000

One GEAR_USAGE entry can now hold many gear items (#1574), the way an
ABSEILING_TRIP entry holds its pitches. The entry row in
``journal_gear_usage_data`` stays: it is what makes a journal a GEAR_USAGE
journal. Its gear item and buffer dates move to ``journal_gear_usage_items``,
one row per (journal, gear item), and every existing row becomes exactly one
item. No event is written, so nothing is pushed to Snipe-IT for the journals
this moves.

The entry's own ``gear_item_id`` / ``checkout_date`` / ``checkin_date`` are kept
for now as a mirror of the entry's first item, so a reader not yet moved to the
items table keeps working; ``gear_item_id`` becomes nullable for an entry with
no items. A later migration drops them.

Items keep the order they were given in (``position``). Their ``journal_id``
cascades on update as well as delete: merging journals moves an entry by
rewriting its ``journal_id``. Deleting a gear item removes only its item; the
mirror's foreign key no longer cascades to the whole entry, so the other items
survive (the mirror is left NULL until the entry is next written).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0119"
down_revision: str | None = "0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIRROR_FK = "journal_gear_usage_data_gear_item_id_fkey"


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "journal_gear_usage_items",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey(
                "journal_gear_usage_data.journal_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "gear_item_id",
            sa.UUID(),
            sa.ForeignKey("gear_items.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
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
        "ix_journal_gear_usage_items_gear_item_id",
        "journal_gear_usage_items",
        ["gear_item_id"],
    )
    op.execute(
        """
        INSERT INTO journal_gear_usage_items (
            journal_id, gear_item_id, checkout_date, checkin_date,
            created_at, updated_at
        )
        SELECT journal_id, gear_item_id, checkout_date, checkin_date,
               created_at, updated_at
        FROM journal_gear_usage_data
        """
    )
    op.alter_column("journal_gear_usage_data", "gear_item_id", nullable=True)
    _replace_mirror_fk(ondelete="SET NULL")


def _replace_mirror_fk(*, ondelete: str) -> None:
    op.drop_constraint(_MIRROR_FK, "journal_gear_usage_data", type_="foreignkey")
    op.create_foreign_key(
        _MIRROR_FK,
        "journal_gear_usage_data",
        "gear_items",
        ["gear_item_id"],
        ["id"],
        ondelete=ondelete,
    )


def downgrade() -> None:
    """Downgrade database schema.

    The mirror is refreshed from each entry's first item (it can be NULL after a
    gear item was deleted), then an entry with no items at all — which the old
    schema cannot hold — is removed. Items beyond the first are dropped with
    their table.
    """
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
    op.execute("DELETE FROM journal_gear_usage_data WHERE gear_item_id IS NULL")
    _replace_mirror_fk(ondelete="CASCADE")
    op.alter_column("journal_gear_usage_data", "gear_item_id", nullable=False)
    op.drop_index(
        "ix_journal_gear_usage_items_gear_item_id",
        table_name="journal_gear_usage_items",
    )
    op.drop_table("journal_gear_usage_items")
