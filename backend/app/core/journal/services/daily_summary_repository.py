"""Repository interface for journal daily summary operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from core_shared.models.journals.daily_summary import JournalDailySummary


class JournalDailySummaryRepository(ABC):
    """Repository interface for journal daily summary persistence."""

    @abstractmethod
    async def find_by_user_and_date(
        self, user_id: str, summary_date: date
    ) -> JournalDailySummary | None:
        """Find a daily summary by user ID and date.

        Args:
            user_id: The user ID to look up
            summary_date: The date to look up

        Returns:
            The JournalDailySummary if found, None otherwise
        """
        pass

    @abstractmethod
    async def upsert(self, summary: JournalDailySummary) -> JournalDailySummary:
        """Create or update a daily summary.

        Uses INSERT ON CONFLICT to handle the unique (user_id, summary_date) constraint.

        Args:
            summary: The summary to upsert

        Returns:
            The upserted summary with updated timestamps and ID
        """
        pass

    @abstractmethod
    async def update_status(
        self, user_id: str, summary_date: date, status: str
    ) -> JournalDailySummary | None:
        """Update the status of a daily summary.

        Args:
            user_id: The user ID
            summary_date: The date
            status: The new status value

        Returns:
            The updated summary, or None if not found
        """
        pass

    @abstractmethod
    async def claim_for_generation(
        self,
        user_id: str,
        summary_date: date,
        *,
        seen_generated_at: datetime | None,
    ) -> bool:
        """Atomically mark the summary GENERATING, if it is still as the caller saw it.

        The marker two concurrent readers race for: exactly one wins. Creates
        the row if none exists; on an existing row only the status moves, so
        text, counters and ``generated_at`` from the previous generation are
        kept until the new one replaces them.

        A claim is a compare-and-set on ``generated_at``: it loses not only
        when the row is already GENERATING but when ``generated_at`` no longer
        equals what the caller saw at its cache check — every completed
        generation moves it, so a slow caller cannot regenerate over a result
        another run has finished in the meantime.

        Args:
            user_id: The user ID
            summary_date: The date
            seen_generated_at: The ``generated_at`` of the row the caller read
                before deciding to generate, or ``None`` if it saw no row (or
                a row that had never generated).

        Returns:
            True if this caller claimed the row; False if it was already
            GENERATING or has been generated since, in which case nothing
            changed.
        """
        pass

    @abstractmethod
    async def invalidate_for_date(self, user_id: str, summary_date: date) -> None:
        """Invalidate (set to PENDING) a daily summary for a date.

        This is a no-op if no summary exists for the date.

        The single-day case of :meth:`invalidate_for_range`, kept as its own
        name for the reason ``local_day_window`` is kept beside ``local_window``:
        "this day's summary" is what most callers are asking for, and passing
        the same date twice reads as a mistake.

        Args:
            user_id: The user ID
            summary_date: The date to invalidate
        """
        pass

    @abstractmethod
    async def complete_generation(
        self,
        summary: JournalDailySummary,
        *,
        seen_invalidated_at: datetime | None,
    ) -> JournalDailySummary | None:
        """Write a finished summary, unless its inputs went stale while it ran.

        The write that closes ITER18-005 Phase 7's race. ``get_or_generate``
        reads the row, assembles the day's inputs and only then claims the row —
        and ``claim_for_generation`` compares ``generated_at``, which an
        invalidation does not move. So an input change landing in that window
        leaves a ``PENDING`` marker that the finishing generation would
        otherwise overwrite with a summary of the *old* inputs.

        A status guard cannot catch it: by this point the row **is**
        ``GENERATING``, because this caller claimed it. What catches it is
        ``invalidated_at``, read with the row before assembly and compared here.

        Args:
            summary: The finished summary to write
            seen_invalidated_at: The row's ``invalidated_at`` as the caller saw
                it **before assembling its inputs**, or ``None`` if it saw no
                row. Compared with ``IS NOT DISTINCT FROM``, so a never-
                invalidated row matches a caller that saw none.

        Returns:
            The written summary, or ``None`` when the write was refused because
            the row was invalidated in the meantime — in which case it is left
            ``PENDING`` and the next read regenerates it.
        """
        pass

    @abstractmethod
    async def user_ids_with_summaries(self) -> list[str]:
        """Every user that has at least one daily summary row.

        The bound an important-date change is applied over. Those events name no
        user — ``contacts`` carries no owner column — and invalidation only ever
        touches rows that exist, so the users who *can* be affected are exactly
        the users who already have a summary. Answering from this table rather
        than from an account listing keeps that true by construction.

        Returns:
            The distinct user ids, each once.
        """
        pass

    @abstractmethod
    async def invalidate_for_range(
        self, user_id: str, first_day: date, last_day: date
    ) -> None:
        """Invalidate (set to PENDING) every summary in a span of days.

        Both ends are **inclusive**, matching ``DaySpan`` and
        ``UpcomingWindow`` — one convention across the phase rather than an
        off-by-one at every boundary between them.

        A span rather than a date because a journal occupies a span: the day
        query selects by overlap, so a journal running Friday to Sunday is part
        of three days' summaries and a change to it makes three stale. Doing
        that as one statement is also what makes an unbounded span safe — it
        touches only rows that already exist, and creates none, so the ``WHERE``
        clause is the bound and no cap on the span's length is needed.

        Args:
            user_id: The user ID
            first_day: The first day of the span, inclusive
            last_day: The last day of the span, inclusive
        """
        pass
