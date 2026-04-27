"""Repository interface for journal daily summary operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

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
    async def invalidate_for_date(self, user_id: str, summary_date: date) -> None:
        """Invalidate (set to PENDING) a daily summary for a date.

        This is a no-op if no summary exists for the date.

        Args:
            user_id: The user ID
            summary_date: The date to invalidate
        """
        pass
