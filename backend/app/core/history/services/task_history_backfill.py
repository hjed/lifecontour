"""One-shot repair of task history, run at application startup.

Two things need fixing, and they have the same source, so they are done
together rather than by two mechanisms that could disagree about what a task's
history should say.

**Historic task events were skip-acknowledged, not replayed.** A deployed
``history-projection`` consumer group has been reading task events since
ITER18-003 Phase 1 and acknowledging them as non-matching, because none of its
patterns matched them. Phases 6 and 7 widened those patterns — but a consumer
group sees each message exactly once, so widening them projects events published
*after* the deploy and nothing before it. Every task that already existed has no
history at all, and nothing will ever redeliver its events.

**Rows already projected carry no owner.** ``field_history.user_id`` did not
exist when they were written, and the task-scoped read cannot authorise a row
that does not say whose it is.

The information is not lost in either case: ``outbox_events`` retains every
event forever — the relay only stamps ``relayed_at``, and nothing prunes the
table — and every task event's payload carries ``user_id``. So the repair reads
the retained events and puts them back through the **same** ``HistoryService``
the live projection uses. That is why this is application code rather than SQL
in a migration: re-spelling the event-to-rows mapping in SQL would be a second
place for it to disagree with the consumer, and this iteration has already
recorded what that costs.

**Safe to run on every start, and it does.** Writes go through
``record_change``'s ``ON CONFLICT (event_id, entity_type, entity_id, field_name)
DO NOTHING``, so re-projecting an event that is already projected writes
nothing, and overlapping with the live consumer is a no-op rather than a race.
The work is bounded by an anti-join against ``field_history``, so once the
repair is done a start costs one indexed query returning no rows.

*One event shape is re-examined on every start:* one that legitimately projects
**no** rows, since the anti-join can never see evidence that it was handled. No
write path publishes such an event today — every task event type produces at
least one row — so the steady-state cost of that is nil, and the alternative
(recording that an event was considered) would be a second bookkeeping table for
a case that does not arise.

*And one assumption is worth naming:* the anti-join treats **any** row bearing an
event's id as proof that the whole event was projected, so an event whose rows
landed only partially would be skipped and stay incomplete. That cannot happen
here — the consumer writes all of an event's rows inside one
``engine.begin()``, so the set is atomic, and nothing deletes ``field_history``
rows except the contact merge's re-point, which touches contact rows only. The
alternative (comparing counts per event) would mean re-deriving each event's row
count outside ``HistoryService``, which is the duplication this whole module
exists to avoid.
"""

import json
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.services.history_service import HistoryService
from app.infrastructure.events.history_projection_consumer import (
    TASK_HISTORY_EVENT_TYPES,
)
from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)

# How many retained events to pull through the projection at a time. The repair
# runs before the application starts serving, so this trades a slightly longer
# start for a bounded working set.
_BATCH_SIZE = 200

# Retained task events that no ``field_history`` row claims. The anti-join is
# what makes this cheap in the steady state: the dedup index leads on
# ``event_id``, so a repaired database answers it without reading rows. The
# ``id`` cursor rather than a bare ``LIMIT`` is what makes the loop terminate —
# an event projecting no rows would otherwise be re-fetched forever.
_UNPROJECTED_TASK_EVENTS = text(
    """
    SELECT o.id, o.event_id, o.event_type, o.aggregate_id, o.event_data,
           o.occurred_at, o.created_at, o.retry_count
    FROM outbox_events o
    WHERE o.event_type = ANY(:event_types)
      AND o.id > :after_id
      AND NOT EXISTS (
          SELECT 1 FROM field_history fh WHERE fh.event_id = o.event_id
      )
    ORDER BY o.id
    LIMIT :batch_size
    """
)

# The other half: rows the live projection wrote correctly during the window
# between Phases 6/7 and the ownership column. Re-projection cannot reach them —
# they exist, so the anti-join skips them — which is why this is a set-based
# update rather than more replay.
#
# **``event_data`` is ``text``, not ``jsonb``**, so the cast is required rather
# than decorative. Migration ``0001`` created the column as ``Text`` and
# ``outbox_table.py`` says so (`# JSON as text`); ``core_shared``'s ORM model
# disagrees and declares ``JSONB``, which is a pre-existing inconsistency that
# never bit anything because every other reader parses the payload in Python.
# Recorded rather than repaired here: changing the column type is a migration of
# the busiest table in the system and has nothing to do with this phase.
#
# The presence test is ``->> 'user_id' IS NOT NULL`` rather than the ``?``
# containment operator, for two reasons: a literal ``?`` in a ``text()``
# statement collides with the driver's parameter marker, and this form also
# rejects a payload carrying a JSON ``null``, which ``?`` would accept and then
# write as NULL anyway.
_FILL_MISSING_OWNERS = text(
    """
    UPDATE field_history fh
    SET user_id = oe.event_data::jsonb ->> 'user_id'
    FROM outbox_events oe
    WHERE fh.event_id = oe.event_id
      AND fh.entity_type = 'task'
      AND fh.user_id IS NULL
      AND oe.event_data::jsonb ->> 'user_id' IS NOT NULL
    """
)


@dataclass(frozen=True)
class TaskHistoryBackfillResult:
    """What one run did, for the log line and for the tests."""

    events_examined: int
    rows_written: int
    owners_filled: int

    @property
    def repaired_anything(self) -> bool:
        return bool(self.rows_written or self.owners_filled)


class TaskHistoryBackfill:
    """Re-projects retained task events and fills in missing row ownership."""

    def __init__(self, history_service: HistoryService | None = None) -> None:
        # The same mapping the consumer uses, not a copy of it. Injectable so a
        # test can watch what it was asked to project.
        self._history_service = history_service or HistoryService()

    @transactional
    async def run(self, transaction: AsyncConnection) -> TaskHistoryBackfillResult:
        """Repair task history on ``transaction``, committing as one unit of work.

        Re-projection runs first so that a repaired row arrives with its owner
        already on it; the owner fill then only has to cover rows that were
        written before the column existed.
        """
        repository = SqlFieldHistoryRepository(transaction)
        events_examined = 0
        rows_written = 0
        after_id = 0

        while True:
            rows = (
                await transaction.execute(
                    _UNPROJECTED_TASK_EVENTS,
                    {
                        "event_types": list(TASK_HISTORY_EVENT_TYPES),
                        "after_id": after_id,
                        "batch_size": _BATCH_SIZE,
                    },
                )
            ).fetchall()
            if not rows:
                break

            for row in rows:
                after_id = int(row.id)
                events_examined += 1
                for entry in self._history_service.project_event(_as_outbox_event(row)):
                    written = await repository.record_change(entry)
                    if written.id is not None:
                        rows_written += 1

        owners_filled = (await transaction.execute(_FILL_MISSING_OWNERS)).rowcount

        result = TaskHistoryBackfillResult(
            events_examined=events_examined,
            rows_written=rows_written,
            owners_filled=int(owners_filled or 0),
        )
        if result.repaired_anything:
            logger.info(
                "Task history backfill repaired historic rows",
                events_examined=result.events_examined,
                rows_written=result.rows_written,
                owners_filled=result.owners_filled,
            )
        return result


def _as_outbox_event(row: Any) -> OutboxEvent:
    """A retained outbox row in the shape ``HistoryService`` projects.

    The live path reaches the same mapping from a stream message; this one comes
    straight off the table it was published to, so the event id, the payload and
    ``occurred_at`` are the originals rather than a round trip through Redis.

    ``event_data`` arrives as a JSON **string**: the column is ``jsonb``, but a
    raw ``text()`` statement carries no type information for the driver to
    decode it with. ``SqlOutboxRepository.get_unrelayed_events`` does the same
    parse for the same reason.
    """
    event_data = row.event_data
    if isinstance(event_data, str):
        event_data = json.loads(event_data)
    return OutboxEvent(
        id=row.id,
        event_id=row.event_id,
        event_type=row.event_type,
        aggregate_id=row.aggregate_id,
        event_data=event_data or {},
        occurred_at=row.occurred_at,
        retry_count=row.retry_count,
        created_at=row.created_at,
    )
