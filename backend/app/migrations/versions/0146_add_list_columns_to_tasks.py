"""add list columns to tasks and relax the journal anchors

Revision ID: 0146
Revises: 0145
Create Date: 2026-11-18 00:00:00.000000

A task may now live on a task list. It gains a list, a position on that list, a
due date, a flag and an icon, and its two journal anchors become nullable,
because a list task needs neither. The CHECKs below are what keep that
relaxation from weakening **journal-only** tasks (spec *Core invariants*):

- ``ck_tasks_journal_only_has_both_anchors`` — invariants 1 and 2. A task with
  no list holds both a creating and a due journal, exactly the guarantee the
  ``NOT NULL`` columns gave before. Invariant 1 (a list or a due journal) is
  implied by it, so a CHECK of its own could never be the one that fails.
- ``ck_tasks_due_date_only_on_list_without_due_journal`` — invariants 4 and 5.
  A due date only on a list task, and never beside a due journal. Invariant 5
  follows from 4 and 2 alone, but is spelled out so the rule reads whole.
- ``ck_tasks_position_only_on_list`` — a task has a position exactly when it is
  on a list; ``ck_tasks_position_non_negative`` matches ``task_lists``.

The list foreign key is ``ON DELETE RESTRICT``, like the journal anchors:
deleting a list deletes some of its tasks and turns others back into
journal-only tasks, both with domain events, so the list-delete service decides
each task's fate and a raw delete can never destroy tasks silently.

Positions are not unique, for the reason ``task_lists`` gives: a task's order on
its list is ``(position, id)``. ``icon`` has no CHECK, for the reason
``task_lists.icon`` gives: the ``TaskIcon`` set is add-only and gated by the
entities. Every CHECK is row-level, so a write that reshapes a task (leaving a
list, say) must change all the related columns in one statement.

The downgrade refuses while any task holds something the 0145 schema cannot
represent — a list, a due date, a flag or an icon — rather than discarding it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0146"
down_revision: str | None = "0145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tasks"
_LIST_FK = "tasks_task_list_id_fkey"
_LIST_INDEX = "ix_tasks_task_list_id_position"
_ANCHORS = ("creating_journal_id", "due_journal_id")
_CHECKS = {
    "ck_tasks_journal_only_has_both_anchors": (
        "task_list_id IS NOT NULL"
        " OR (creating_journal_id IS NOT NULL AND due_journal_id IS NOT NULL)"
    ),
    "ck_tasks_due_date_only_on_list_without_due_journal": (
        "due_date IS NULL OR (task_list_id IS NOT NULL AND due_journal_id IS NULL)"
    ),
    "ck_tasks_position_only_on_list": "(task_list_id IS NULL) = (position IS NULL)",
    "ck_tasks_position_non_negative": "position >= 0",
}
# Rows carrying anything the 0145 schema has no column for.
_UNREPRESENTABLE_ROWS = """
    SELECT count(*) FROM tasks
    WHERE task_list_id IS NOT NULL
       OR due_date IS NOT NULL
       OR flagged
       OR icon IS NOT NULL
"""


def upgrade() -> None:
    """Add the list columns, relax the anchors and add the invariant CHECKs."""
    op.add_column(_TABLE, sa.Column("task_list_id", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("position", sa.Integer(), nullable=True))
    # A calendar day in the user's timezone, with no time of day.
    op.add_column(_TABLE, sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column(
            "flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(_TABLE, sa.Column("icon", sa.String(length=50), nullable=True))

    op.create_foreign_key(
        _LIST_FK, _TABLE, "task_lists", ["task_list_id"], ["id"], ondelete="RESTRICT"
    )
    # Serves a list's tasks in order, and keeps the RESTRICT check on a list
    # delete cheap.
    op.create_index(_LIST_INDEX, _TABLE, ["task_list_id", "position"])

    for anchor in _ANCHORS:
        op.alter_column(_TABLE, anchor, existing_type=sa.Integer(), nullable=True)

    # Every existing row is a journal-only task with both anchors, unflagged and
    # on no list, so each CHECK validates trivially.
    for name, condition in _CHECKS.items():
        op.create_check_constraint(name, _TABLE, condition)


def downgrade() -> None:
    """Remove the list columns and make both anchors mandatory again.

    Refuses rather than discarding data the 0145 schema cannot hold.
    """
    unrepresentable = op.get_bind().execute(sa.text(_UNREPRESENTABLE_ROWS)).scalar()
    if unrepresentable:
        raise RuntimeError(
            f"0146 cannot be downgraded: {unrepresentable} task(s) hold a list, "
            "due date, flag or icon that revision 0145 has no column for. "
            "Remove those values first."
        )

    for name in _CHECKS:
        op.drop_constraint(name, _TABLE, type_="check")
    for anchor in _ANCHORS:
        op.alter_column(_TABLE, anchor, existing_type=sa.Integer(), nullable=False)
    op.drop_index(_LIST_INDEX, table_name=_TABLE)
    op.drop_constraint(_LIST_FK, _TABLE, type_="foreignkey")
    for column in ("icon", "flagged", "due_date", "position", "task_list_id"):
        op.drop_column(_TABLE, column)
