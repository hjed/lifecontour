"""add an ownership column to field_history, for history whose entity may be gone

Revision ID: 0107
Revises: 0106
Create Date: 2026-08-23 00:00:00.000000

Every history read in this system authorises the same way: load the aggregate,
compare ``user_id``. That works for a journal and for a contact because neither
is ever hard-deleted.

**A task is.** ``TaskService.delete_task`` removes the row, and the
``TaskDeleted`` event projects a ``__deleted__`` marker into ``field_history``
— onto a surface that, without this column, could never authorise anybody to
read it. The task-scoped history read (``GET /api/tasks/{id}/history``,
``get_task_history``) has to answer *"is this yours?"* for a task with no row
left, and the only place that answer survives is the event payload: every task
event carries ``user_id``, and ``TaskDeleted`` carries it for precisely this
reason.

The column is **nullable and deliberately half-populated**. Journal and contact
rows carry nothing here and need nothing: stamping them would advertise a check
that does not exist. Only the task projection handlers set it.

**No backfill here.** Two things need repairing at once — task rows already
projected but with no owner, and task events that were *skip-acknowledged* by a
deployed ``history-projection`` consumer group before Phases 6 and 7 widened its
patterns, and which therefore will never be redelivered. The second needs the
event-to-row mapping in ``HistoryService``, and re-spelling that mapping in SQL
would be two places for it to disagree. Both are done together by
``TaskHistoryBackfill``, which runs at application startup, is guarded by an
anti-join against ``field_history`` and is idempotent. See
``app/core/history/services/task_history_backfill.py``.

The index is this revision's other half. ``field_history`` carries indexes on
``field_name`` and ``created_at`` only, and the reads this phase adds — the
owner lookup and the ``'task'`` aggregation predicate — both filter on
``(entity_type, entity_id)``. The journal and contact aggregate reads use the
same shape, so the index pays for those too.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0107"
down_revision: str | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the ownership column and the index the task history read needs."""
    op.add_column(
        "field_history",
        sa.Column("user_id", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "idx_field_history_entity",
        "field_history",
        ["entity_type", "entity_id"],
    )


def downgrade() -> None:
    """Drop both, losing the recorded ownership of deleted tasks' history.

    Reversible in schema but not in meaning: once the column is gone, a
    hard-deleted task's rows have nothing left to say whose they are, and
    re-upgrading recovers them only because ``outbox_events`` retains the events
    forever and the backfill reads them back.
    """
    op.drop_index("idx_field_history_entity", table_name="field_history")
    op.drop_column("field_history", "user_id")
