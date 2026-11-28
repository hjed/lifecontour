"""add recurrence to tasks

Revision ID: 0150
Revises: 0149
Create Date: 2026-11-28 00:00:00.000000

A task on a list may recur: completing it creates the next copy (spec
*Recurring Tasks*). A task gains its **recurrence setting** and, on a copy, the
task it came from:

- ``recurrence_mode`` — ``no_date``, ``interval`` or ``series``; NULL when the
  task does not recur.
- ``recurrence_interval_count`` / ``recurrence_interval_unit`` — *interval after
  completion*, kept as entered ("2 weeks"), not as a PostgreSQL ``interval``,
  which would normalise it and has no month-end rule of its own.
- ``recurrence_series_id`` — *next journal in a series*.
- ``recurrence_of_task_id`` — the task a copy was made from, for the chain in
  history.

The CHECKs keep each mode to its own shape, and ``ck_tasks_recurrence_only_on_list``
is the list half of invariant 6 (the ordinary-list half needs list kinds, which
do not exist yet). Like 0146's, every CHECK is row-level, so a write that takes
a task off its list must clear its recurrence in the same statement.

The series foreign key is ``ON DELETE RESTRICT``: ``SET NULL`` would leave a
series-mode task with no series and fail its own CHECK, and the spec's fallback
to *no date* is a domain change with history, made by the series delete and
merge services before the series row goes. The "recurrence of" link is
``ON DELETE SET NULL``: a copy outlives its original, and history keeps the
chain through its events. It is not unique — an original that kept a changed
copy can recur again — and needs no list CHECK, because a copy never has a
creating journal and so can never become journal-only.

Both partial indexes serve the foreign keys' delete checks as well as later
lookups (a task's copies; the tasks recurring in a series). Owner scoping stays
in the services and repositories, as for ``task_list_id``.

The downgrade refuses while any task recurs or records its original, rather
than discarding either.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0150"
down_revision: str | None = "0149"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tasks"
_SERIES_FK = "fk_tasks_recurrence_series_id"
_ORIGINAL_FK = "fk_tasks_recurrence_of_task_id"
_INDEXES = {
    "ix_tasks_recurrence_series_id": "recurrence_series_id",
    "ix_tasks_recurrence_of_task_id": "recurrence_of_task_id",
}
_IS_INTERVAL = "recurrence_mode IS NOT DISTINCT FROM 'interval'"
_IS_SERIES = "recurrence_mode IS NOT DISTINCT FROM 'series'"
_CHECKS = {
    "ck_tasks_recurrence_only_on_list": (
        "recurrence_mode IS NULL OR task_list_id IS NOT NULL"
    ),
    "ck_tasks_recurrence_mode": (
        "recurrence_mode IN ('no_date', 'interval', 'series')"
    ),
    "ck_tasks_recurrence_interval_matches_mode": (
        f"({_IS_INTERVAL}) = (recurrence_interval_count IS NOT NULL)"
        f" AND ({_IS_INTERVAL}) = (recurrence_interval_unit IS NOT NULL)"
    ),
    "ck_tasks_recurrence_interval_unit": (
        "recurrence_interval_unit IN ('day', 'week', 'month', 'year')"
    ),
    "ck_tasks_recurrence_interval_count_positive": "recurrence_interval_count >= 1",
    "ck_tasks_recurrence_series_matches_mode": (
        f"({_IS_SERIES}) = (recurrence_series_id IS NOT NULL)"
    ),
    "ck_tasks_recurrence_of_not_self": "recurrence_of_task_id <> id",
}
_COLUMN_TYPES: dict[str, sa.types.TypeEngine[Any]] = {
    "recurrence_mode": sa.String(length=20),
    "recurrence_interval_count": sa.Integer(),
    "recurrence_interval_unit": sa.String(length=10),
    "recurrence_series_id": sa.Uuid(as_uuid=True),
    "recurrence_of_task_id": sa.Integer(),
}
_UNREPRESENTABLE_ROWS = """
    SELECT count(*) FROM tasks
    WHERE recurrence_mode IS NOT NULL OR recurrence_of_task_id IS NOT NULL
"""


def upgrade() -> None:
    """Add the recurrence columns, their foreign keys, CHECKs and indexes."""
    for name, column_type in _COLUMN_TYPES.items():
        op.add_column(_TABLE, sa.Column(name, column_type, nullable=True))

    op.create_foreign_key(
        _SERIES_FK,
        _TABLE,
        "journal_series",
        ["recurrence_series_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        _ORIGINAL_FK,
        _TABLE,
        _TABLE,
        ["recurrence_of_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for name, column in _INDEXES.items():
        op.create_index(
            name,
            _TABLE,
            [column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )

    # Every existing row does not recur, so each CHECK validates trivially.
    for name, condition in _CHECKS.items():
        op.create_check_constraint(name, _TABLE, condition)


def downgrade() -> None:
    """Remove recurrence, refusing rather than discarding a setting or a link."""
    unrepresentable = op.get_bind().execute(sa.text(_UNREPRESENTABLE_ROWS)).scalar()
    if unrepresentable:
        raise RuntimeError(
            f"0150 cannot be downgraded: {unrepresentable} task(s) recur or record "
            "the task they were copied from, which revision 0149 has no column "
            "for. Remove those values first."
        )

    for name in _CHECKS:
        op.drop_constraint(name, _TABLE, type_="check")
    for name in _INDEXES:
        op.drop_index(name, table_name=_TABLE)
    op.drop_constraint(_ORIGINAL_FK, _TABLE, type_="foreignkey")
    op.drop_constraint(_SERIES_FK, _TABLE, type_="foreignkey")
    for name in reversed(_COLUMN_TYPES):
        op.drop_column(_TABLE, name)
