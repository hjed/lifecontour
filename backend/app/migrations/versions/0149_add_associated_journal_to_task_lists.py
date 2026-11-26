"""add task_lists.associated_journal_id

Revision ID: 0149
Revises: 0148
Create Date: 2026-11-26 00:00:00.000000

A list may be associated with **one** journal — a packing list for a trip — and
a journal may hold several lists, so this is one nullable column with no
uniqueness.

The foreign key is ``ON DELETE RESTRICT``, as for the task anchors, not
``SET NULL``. Journal delete and merge unassociate or re-point each list
themselves, each with a list-history event, before the journal row goes; the
constraint is only the backstop that makes a path which forgot fail rather than
silently drop the association with no history. Those journal paths land before
anything can write an association, so the constraint never refuses a delete the
product allows.

There is no composite owner key: as with ``tasks.task_list_id``, owner scoping
lives in the services and repositories, which must check that the journal
belongs to the list's owner before associating it.

The partial index serves the lookups by journal — the ``RESTRICT`` check on a
journal delete, and reading a journal's lists — and skips the unassociated
majority.

The downgrade refuses while any list is associated, rather than discarding the
association.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0149"
down_revision: str | None = "0148"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "task_lists"
_COLUMN = "associated_journal_id"
_FK = "fk_task_lists_associated_journal_id"
_INDEX = "ix_task_lists_associated_journal_id"
_ASSOCIATED_LISTS = (
    "SELECT count(*) FROM task_lists WHERE associated_journal_id IS NOT NULL"
)


def upgrade() -> None:
    """Add the column, its RESTRICT foreign key and its partial index."""
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))
    op.create_foreign_key(
        _FK, _TABLE, "journals", [_COLUMN], ["id"], ondelete="RESTRICT"
    )
    op.create_index(
        _INDEX,
        _TABLE,
        [_COLUMN],
        postgresql_where=sa.text(f"{_COLUMN} IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove the association, refusing rather than discarding one."""
    associated = op.get_bind().execute(sa.text(_ASSOCIATED_LISTS)).scalar()
    if associated:
        raise RuntimeError(
            f"0149 cannot be downgraded: {associated} task list(s) are associated "
            "with a journal, which revision 0148 has no column for. "
            "Remove those associations first."
        )

    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, _COLUMN)
