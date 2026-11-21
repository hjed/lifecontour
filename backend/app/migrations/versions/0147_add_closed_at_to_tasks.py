"""add closed_at to tasks

Revision ID: 0147
Revises: 0146
Create Date: 2026-11-21 00:00:00.000000

A list's Completed group shows its done and cancelled tasks most recently closed
first (spec *The list page*). ``updated_at`` cannot order it: every text, flag
or icon edit moves it, so editing a completed task would jump it to the top.
So a task records when it was closed:

- ``closed_at`` is set whenever a task enters a closed status (including done ->
  cancelled, which is a fresh close) and cleared when it is reopened.
  ``SqlTaskRepository.save`` maintains it; nothing else writes a task's status.
- ``ck_tasks_closed_at_matches_status`` ties it to the status, so a closed task
  always has a close time and an open one never does.
- ``ix_tasks_task_list_id_closed_at`` serves a list's Completed page in order;
  it is partial because open tasks never appear there.

Existing closed tasks are backfilled from ``updated_at``, the closest record of
their close there is. Every one of them is a journal-only task today, so no list
shows that approximation yet.

The downgrade drops the column and loses only the close order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0147"
down_revision: str | None = "0146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tasks"
_CHECK = "ck_tasks_closed_at_matches_status"
_INDEX = "ix_tasks_task_list_id_closed_at"


def upgrade() -> None:
    """Add ``closed_at``, backfill it, then constrain and index it."""
    op.add_column(
        _TABLE, sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE tasks SET closed_at = updated_at WHERE status IN ('done', 'cancelled')"
    )
    op.create_check_constraint(
        _CHECK, _TABLE, "(status = 'not_done') = (closed_at IS NULL)"
    )
    op.create_index(
        _INDEX,
        _TABLE,
        ["task_list_id", sa.text("closed_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("closed_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove ``closed_at`` with its CHECK and index."""
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "closed_at")
