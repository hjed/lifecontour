"""Integration tests for SqlJournalDailySummaryRepository."""

from datetime import UTC, date, datetime

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary

from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)


@pytest.fixture
def daily_summary_repo(async_connection):
    """Provide a SqlJournalDailySummaryRepository using the test connection."""
    return SqlJournalDailySummaryRepository(async_connection)


class TestSqlJournalDailySummaryRepository:
    """Integration tests for daily summary CRUD operations."""

    @pytest.mark.asyncio
    async def test_find_by_user_and_date_returns_none_when_empty(
        self, daily_summary_repo
    ):
        """Returns None for a non-existent summary."""
        result = await daily_summary_repo.find_by_user_and_date(
            "user123", date(2026, 4, 27)
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_creates_new_summary(self, daily_summary_repo):
        """Upsert creates a new summary when none exists."""
        summary = JournalDailySummary(
            user_id="user_integ_test",
            summary_date=date(2026, 4, 27),
            summary_text="A productive day.",
            journal_count=3,
            event_count=1,
            contact_count=2,
            mood_average=7.5,
            status=SummaryStatus.GENERATED,
            generated_at=datetime.now(tz=UTC),
        )

        result = await daily_summary_repo.upsert(summary)

        assert result.id is not None
        assert result.user_id == "user_integ_test"
        assert result.summary_date == date(2026, 4, 27)
        assert result.summary_text == "A productive day."
        assert result.journal_count == 3
        assert result.event_count == 1
        assert result.contact_count == 2
        assert result.mood_average == 7.5
        assert result.status == SummaryStatus.GENERATED
        assert result.generated_at is not None
        assert result.created_at is not None
        assert result.updated_at is not None

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_summary(self, daily_summary_repo):
        """Upsert updates an existing summary on the same (user_id, date)."""
        # Create initial summary
        summary = JournalDailySummary(
            user_id="user_integ_test_2",
            summary_date=date(2026, 4, 27),
            summary_text="First version.",
            journal_count=2,
            status=SummaryStatus.GENERATED,
        )
        initial = await daily_summary_repo.upsert(summary)
        initial_id = initial.id

        # Update
        updated_summary = JournalDailySummary(
            user_id="user_integ_test_2",
            summary_date=date(2026, 4, 27),
            summary_text="Updated version.",
            journal_count=5,
            status=SummaryStatus.GENERATED,
        )
        result = await daily_summary_repo.upsert(updated_summary)

        assert result.id == initial_id
        assert result.summary_text == "Updated version."
        assert result.journal_count == 5

    @pytest.mark.asyncio
    async def test_find_by_user_and_date_returns_existing(self, daily_summary_repo):
        """Find returns an existing summary."""
        summary = JournalDailySummary(
            user_id="user_find_test",
            summary_date=date(2026, 4, 27),
            summary_text="Test summary.",
            journal_count=2,
            event_count=1,
            contact_count=0,
            mood_average=6.0,
            status=SummaryStatus.GENERATED,
        )
        await daily_summary_repo.upsert(summary)

        result = await daily_summary_repo.find_by_user_and_date(
            "user_find_test", date(2026, 4, 27)
        )

        assert result is not None
        assert result.user_id == "user_find_test"
        assert result.summary_date == date(2026, 4, 27)
        assert result.summary_text == "Test summary."
        assert result.status == SummaryStatus.GENERATED

    @pytest.mark.asyncio
    async def test_update_status(self, daily_summary_repo):
        """Update status changes the status field."""
        # Create a summary first
        summary = JournalDailySummary(
            user_id="user_status_test",
            summary_date=date(2026, 4, 27),
            summary_text="Status test.",
            status=SummaryStatus.GENERATED,
        )
        await daily_summary_repo.upsert(summary)

        # Update status
        result = await daily_summary_repo.update_status(
            "user_status_test", date(2026, 4, 27), SummaryStatus.PENDING.value
        )

        assert result is not None
        assert result.status == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_update_status_returns_none_for_missing(self, daily_summary_repo):
        """Update status returns None if no summary exists."""
        result = await daily_summary_repo.update_status(
            "nonexistent_user", date(2026, 4, 27), SummaryStatus.PENDING.value
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_for_date_sets_to_pending(self, daily_summary_repo):
        """Invalidate sets an existing summary to PENDING."""
        # Create a GENERATED summary
        summary = JournalDailySummary(
            user_id="user_invalidate_test",
            summary_date=date(2026, 4, 27),
            summary_text="Will be invalidated.",
            status=SummaryStatus.GENERATED,
        )
        await daily_summary_repo.upsert(summary)

        # Invalidate
        await daily_summary_repo.invalidate_for_date(
            "user_invalidate_test", date(2026, 4, 27)
        )

        # Verify it's now PENDING
        result = await daily_summary_repo.find_by_user_and_date(
            "user_invalidate_test", date(2026, 4, 27)
        )
        assert result is not None
        assert result.status == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_invalidate_for_date_noop_when_no_summary(self, daily_summary_repo):
        """Invalidate is a no-op when no summary exists."""
        # Should not raise
        await daily_summary_repo.invalidate_for_date(
            "nonexistent_user", date(2026, 4, 27)
        )

    @pytest.mark.asyncio
    async def test_invalidate_for_date_noop_when_already_pending(
        self, daily_summary_repo
    ):
        """Invalidate is a no-op when already PENDING."""
        summary = JournalDailySummary(
            user_id="user_already_pending",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.PENDING,
        )
        await daily_summary_repo.upsert(summary)

        # Should not raise
        await daily_summary_repo.invalidate_for_date(
            "user_already_pending", date(2026, 4, 27)
        )

        result = await daily_summary_repo.find_by_user_and_date(
            "user_already_pending", date(2026, 4, 27)
        )
        assert result is not None
        assert result.status == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_different_dates_for_same_user(self, daily_summary_repo):
        """Different dates produce separate summaries."""
        for d in [date(2026, 4, 25), date(2026, 4, 26), date(2026, 4, 27)]:
            summary = JournalDailySummary(
                user_id="user_multi_date",
                summary_date=d,
                summary_text=f"Summary for {d}",
                status=SummaryStatus.GENERATED,
            )
            await daily_summary_repo.upsert(summary)

        for d in [date(2026, 4, 25), date(2026, 4, 26), date(2026, 4, 27)]:
            result = await daily_summary_repo.find_by_user_and_date(
                "user_multi_date", d
            )
            assert result is not None
            assert result.summary_text == f"Summary for {d}"

    @pytest.mark.asyncio
    async def test_different_users_for_same_date(self, daily_summary_repo):
        """Different users on the same date are isolated."""
        for uid in ["user_a", "user_b"]:
            summary = JournalDailySummary(
                user_id=uid,
                summary_date=date(2026, 4, 27),
                summary_text=f"Summary for {uid}",
                status=SummaryStatus.GENERATED,
            )
            await daily_summary_repo.upsert(summary)

        for uid in ["user_a", "user_b"]:
            result = await daily_summary_repo.find_by_user_and_date(
                uid, date(2026, 4, 27)
            )
            assert result is not None
            assert result.summary_text == f"Summary for {uid}"
