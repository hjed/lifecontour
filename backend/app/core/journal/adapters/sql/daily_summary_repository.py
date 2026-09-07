"""SQL implementation of JournalDailySummaryRepository."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.daily_summary_repository import (
    JournalDailySummaryRepository,
)


class SqlJournalDailySummaryRepository(JournalDailySummaryRepository):
    """SQL implementation using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.conn = connection

    def _row_to_entity(self, row: Any) -> JournalDailySummary:
        """Convert a database row to a JournalDailySummary domain entity."""
        return JournalDailySummary(
            id=row.id,
            user_id=row.user_id,
            summary_date=row.summary_date,
            summary_text=row.summary_text,
            journal_count=row.journal_count,
            event_count=row.event_count,
            contact_count=row.contact_count,
            mood_average=float(row.mood_average)
            if row.mood_average is not None
            else None,
            status=SummaryStatus(row.status),
            generated_at=row.generated_at,
            invalidated_at=row.invalidated_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_user_and_date(
        self, user_id: str, summary_date: date
    ) -> JournalDailySummary | None:
        """Find a daily summary by user ID and date."""
        query = text(
            """
            SELECT id, user_id, summary_date, summary_text,
                   journal_count, event_count, contact_count, mood_average,
                   status, generated_at, invalidated_at, created_at, updated_at
            FROM journal_daily_summaries
            WHERE user_id = :user_id AND summary_date = :summary_date
        """
        )
        result = await self.conn.execute(
            query, {"user_id": user_id, "summary_date": summary_date}
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    async def upsert(self, summary: JournalDailySummary) -> JournalDailySummary:
        """Create or update a daily summary using INSERT ON CONFLICT."""
        query = text(
            """
            INSERT INTO journal_daily_summaries
                (user_id, summary_date, summary_text,
                 journal_count, event_count, contact_count, mood_average,
                 status, generated_at)
            VALUES
                (:user_id, :summary_date, :summary_text,
                 :journal_count, :event_count, :contact_count, :mood_average,
                 :status, :generated_at)
            ON CONFLICT (user_id, summary_date) DO UPDATE SET
                summary_text = EXCLUDED.summary_text,
                journal_count = EXCLUDED.journal_count,
                event_count = EXCLUDED.event_count,
                contact_count = EXCLUDED.contact_count,
                mood_average = EXCLUDED.mood_average,
                status = EXCLUDED.status,
                generated_at = EXCLUDED.generated_at,
                updated_at = NOW()
            RETURNING id, created_at, updated_at
        """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": summary.user_id,
                "summary_date": summary.summary_date,
                "summary_text": summary.summary_text,
                "journal_count": summary.journal_count,
                "event_count": summary.event_count,
                "contact_count": summary.contact_count,
                "mood_average": summary.mood_average,
                "status": str(summary.status),
                "generated_at": summary.generated_at,
            },
        )
        row = result.fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert journal daily summary")
        summary.id = row.id
        summary.created_at = row.created_at
        summary.updated_at = row.updated_at
        return summary

    async def update_status(
        self, user_id: str, summary_date: date, status: str
    ) -> JournalDailySummary | None:
        """Update the status of a daily summary."""
        query = text(
            """
            UPDATE journal_daily_summaries
            SET status = :status, updated_at = NOW()
            WHERE user_id = :user_id AND summary_date = :summary_date
            RETURNING id, user_id, summary_date, summary_text,
                      journal_count, event_count, contact_count, mood_average,
                      status, generated_at, invalidated_at, created_at, updated_at
        """
        )
        result = await self.conn.execute(
            query,
            {"user_id": user_id, "summary_date": summary_date, "status": status},
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    async def claim_for_generation(
        self,
        user_id: str,
        summary_date: date,
        *,
        seen_generated_at: datetime | None,
    ) -> bool:
        """Atomically mark the summary GENERATING, if it is still as the caller saw it.

        One statement, so two callers cannot both win: the insert takes the
        unique (user_id, summary_date) slot or, on conflict, updates the row
        under its lock — and the conflict branch's WHERE lets through untouched,
        returning nothing, a row that is already GENERATING or whose
        ``generated_at`` has moved since the caller looked (``IS NOT DISTINCT
        FROM`` so a never-generated row matches a caller that saw none). Only
        the status moves on an existing row.
        """
        query = text(
            """
            INSERT INTO journal_daily_summaries (user_id, summary_date, status)
            VALUES (:user_id, :summary_date, :generating)
            ON CONFLICT (user_id, summary_date) DO UPDATE
                SET status = EXCLUDED.status, updated_at = NOW()
                WHERE journal_daily_summaries.status != EXCLUDED.status
                  AND journal_daily_summaries.generated_at IS NOT DISTINCT FROM
                      CAST(:seen_generated_at AS TIMESTAMP WITH TIME ZONE)
            RETURNING id
        """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": user_id,
                "summary_date": summary_date,
                "generating": SummaryStatus.GENERATING.value,
                "seen_generated_at": seen_generated_at,
            },
        )
        return result.fetchone() is not None

    async def invalidate_for_date(self, user_id: str, summary_date: date) -> None:
        """Set an existing summary to PENDING. No-op if none exists.

        The one-day span, delegated rather than written twice: two statements
        that must agree about what "invalidate" means is one more than there
        needs to be.
        """
        await self.invalidate_for_range(user_id, summary_date, summary_date)

    async def complete_generation(
        self,
        summary: JournalDailySummary,
        *,
        seen_invalidated_at: datetime | None,
    ) -> JournalDailySummary | None:
        """Write the finished summary, unless the row was invalidated since.

        An ``UPDATE`` rather than the upsert, because the row is guaranteed to
        exist: this caller claimed it. Two predicates guard it, and they answer
        different questions — the status, that this generation still holds the
        claim, and ``invalidated_at``, that nothing changed the day's inputs
        after they were gathered. ``IS NOT DISTINCT FROM`` so a row that has
        never been invalidated matches a caller that saw none.

        Returning nothing means the write was refused, and the row is left as it
        is — ``PENDING`` — so the next read regenerates from current inputs.
        """
        query = text(
            """
            UPDATE journal_daily_summaries
            SET summary_text = :summary_text,
                journal_count = :journal_count,
                event_count = :event_count,
                contact_count = :contact_count,
                mood_average = :mood_average,
                status = :status,
                generated_at = :generated_at,
                updated_at = NOW()
            WHERE user_id = :user_id
              AND summary_date = :summary_date
              AND status = :generating
              AND invalidated_at IS NOT DISTINCT FROM
                  CAST(:seen_invalidated_at AS TIMESTAMP WITH TIME ZONE)
            RETURNING id, user_id, summary_date, summary_text,
                      journal_count, event_count, contact_count, mood_average,
                      status, generated_at, invalidated_at, created_at, updated_at
        """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": summary.user_id,
                "summary_date": summary.summary_date,
                "summary_text": summary.summary_text,
                "journal_count": summary.journal_count,
                "event_count": summary.event_count,
                "contact_count": summary.contact_count,
                "mood_average": summary.mood_average,
                "status": str(summary.status),
                "generated_at": summary.generated_at,
                "generating": SummaryStatus.GENERATING.value,
                "seen_invalidated_at": seen_invalidated_at,
            },
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    async def release_claim(self, user_id: str, summary_date: date) -> bool:
        """Move a ``GENERATING`` row back to ``PENDING``. One statement.

        ``invalidated_at`` moves with it, for the reason
        :meth:`invalidate_for_range` gives: a request already assembling inputs
        for this day must be able to see that the claim it is about to write
        against has been released.
        """
        result = await self.conn.execute(
            text(
                """
                UPDATE journal_daily_summaries
                SET status = :pending,
                    invalidated_at = clock_timestamp(),
                    updated_at = NOW()
                WHERE user_id = :user_id
                  AND summary_date = :summary_date
                  AND status = :generating
                RETURNING id
            """
            ),
            {
                "user_id": user_id,
                "summary_date": summary_date,
                "pending": SummaryStatus.PENDING.value,
                "generating": SummaryStatus.GENERATING.value,
            },
        )
        return result.fetchone() is not None

    async def user_ids_with_summaries(self) -> list[str]:
        """Every user with at least one summary row, each once.

        ``DISTINCT`` over the leading column of the ``(user_id, summary_date)``
        unique index, so this is an index scan rather than a table one.
        """
        result = await self.conn.execute(
            text("SELECT DISTINCT user_id FROM journal_daily_summaries")
        )
        return [row.user_id for row in result.fetchall()]

    async def invalidate_for_range(
        self, user_id: str, first_day: date, last_day: date
    ) -> None:
        """Set every existing summary in the span to PENDING.

        ``BETWEEN`` is inclusive at both ends, which is what makes the span's
        last day part of it — the same convention ``DaySpan`` and
        ``UpcomingWindow`` carry.

        The statement creates nothing: a day with no summary row has nothing to
        make stale, and inserting a ``PENDING`` marker for it would manufacture
        a row for a day the user may never open. That is also why an unbounded
        span is safe here and needs no cap.

        **An already-``PENDING`` row is written again, deliberately.** Skipping
        it would save an ``UPDATE`` and reopen the race ``invalidated_at``
        exists to close: a request that read a stale row and is assembling its
        inputs would not see the change, because the stamp it compares against
        at persist would not have moved. The saving was never the point — four
        ticks costing one *regeneration* is, and that holds regardless, because
        none of these writes generates anything.

        **``clock_timestamp()`` rather than ``NOW()``, and the difference is
        load-bearing.** ``NOW()`` is the *transaction's* start time, so two
        invalidations inside one transaction stamp the row identically and the
        persist guard cannot tell them apart — it would compare equal and allow
        a write of inputs gathered before the second one. ``clock_timestamp()``
        advances within a transaction, which is what "when this row was marked"
        actually means. It is also the only form under which the guard is
        *testable*: the integration fixture runs a whole test in one
        transaction, so every ``NOW()`` in it returns the same instant.
        """
        query = text(
            """
            UPDATE journal_daily_summaries
            SET status = :status,
                invalidated_at = clock_timestamp(),
                updated_at = NOW()
            WHERE user_id = :user_id
              AND summary_date BETWEEN :first_day AND :last_day
        """
        )
        await self.conn.execute(
            query,
            {
                "user_id": user_id,
                "first_day": first_day,
                "last_day": last_day,
                "status": SummaryStatus.PENDING.value,
            },
        )
