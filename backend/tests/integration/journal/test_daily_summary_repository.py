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


class TestClaimForGeneration:
    """The atomic GENERATING claim two concurrent readers race for.

    Exactly one caller may win a claim on a row that is not already generating
    and still carries the ``generated_at`` the caller saw at its cache check; a
    claim on a row that is generating, or that another run has since finished,
    answers ``False`` and changes nothing. That is the property
    ``DailySummaryService`` relies on to call the AI once when two stale reads
    pass the cache check together, however far apart they run.
    """

    _USER = "user_claim_test"
    _DATE = date(2026, 4, 27)

    @pytest.mark.asyncio
    async def test_claims_a_row_that_does_not_exist_yet(self, daily_summary_repo):
        claimed = await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )

        assert claimed is True
        row = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert row is not None
        assert row.status == SummaryStatus.GENERATING

    @pytest.mark.asyncio
    async def test_claims_a_generated_row_and_keeps_what_it_held(
        self, daily_summary_repo
    ):
        """Only the status moves: text, counters and generated_at stay."""
        generated_at = datetime(2026, 4, 26, 22, 0, tzinfo=UTC)
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=self._DATE,
                summary_text="Last night's.",
                journal_count=3,
                status=SummaryStatus.GENERATED,
                generated_at=generated_at,
            )
        )

        claimed = await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=generated_at
        )

        assert claimed is True
        row = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert row is not None
        assert row.status == SummaryStatus.GENERATING
        assert row.summary_text == "Last night's."
        assert row.journal_count == 3
        assert row.generated_at == generated_at

    @pytest.mark.asyncio
    async def test_a_second_claim_on_a_generating_row_loses(self, daily_summary_repo):
        assert await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )

        claimed_again = await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )

        assert claimed_again is False
        row = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert row is not None
        assert row.status == SummaryStatus.GENERATING

    @pytest.mark.asyncio
    async def test_a_row_released_from_generating_can_be_claimed_again(
        self, daily_summary_repo
    ):
        """A FAILED run must not hold the row forever."""
        assert await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )
        await daily_summary_repo.update_status(
            self._USER, self._DATE, SummaryStatus.FAILED.value
        )

        assert await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )

    @pytest.mark.asyncio
    async def test_a_claim_is_scoped_to_one_user_and_day(self, daily_summary_repo):
        assert await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )

        assert await daily_summary_repo.claim_for_generation(
            self._USER, date(2026, 4, 28), seen_generated_at=None
        )
        assert await daily_summary_repo.claim_for_generation(
            "someone_else", self._DATE, seen_generated_at=None
        )

    @pytest.mark.asyncio
    async def test_a_claim_loses_when_another_run_finished_since_it_looked(
        self, daily_summary_repo
    ):
        """The slow-reader case: the row was regenerated between look and claim.

        The claim carries the ``generated_at`` the caller saw; a row whose
        ``generated_at`` has moved is somebody else's fresh result, and it is
        left exactly as it is.
        """
        seen = datetime(2026, 4, 26, 22, 0, tzinfo=UTC)
        finished_since = datetime(2026, 4, 27, 7, 5, tzinfo=UTC)
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=self._DATE,
                summary_text="The other run's fresh result.",
                status=SummaryStatus.GENERATED,
                generated_at=finished_since,
            )
        )

        claimed = await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=seen
        )

        assert claimed is False
        row = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert row is not None
        assert row.status == SummaryStatus.GENERATED
        assert row.summary_text == "The other run's fresh result."
        assert row.generated_at == finished_since

    @pytest.mark.asyncio
    async def test_a_claim_that_saw_no_row_loses_to_a_row_generated_since(
        self, daily_summary_repo
    ):
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=self._DATE,
                summary_text="Generated while the caller was on its way.",
                status=SummaryStatus.GENERATED,
                generated_at=datetime(2026, 4, 27, 7, 5, tzinfo=UTC),
            )
        )

        claimed = await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )

        assert claimed is False
        row = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert row is not None
        assert row.status == SummaryStatus.GENERATED

    @pytest.mark.asyncio
    async def test_a_claim_that_saw_no_row_wins_a_failed_row_that_never_generated(
        self, daily_summary_repo
    ):
        """A FAILED run leaves no ``generated_at``, so nothing has moved."""
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER, summary_date=self._DATE, status=SummaryStatus.FAILED
            )
        )

        assert await daily_summary_repo.claim_for_generation(
            self._USER, self._DATE, seen_generated_at=None
        )


class TestInvalidatingASpanOfDays:
    """A journal occupies a span of days, so invalidation works in ranges.

    ``get_all`` selects a day's journals by overlap, so a journal running Friday
    to Sunday is part of three days' summaries. Doing that as one statement
    rather than a loop over enumerated dates is what lets a span of any length
    cost one round trip and touch only the rows that exist — an unbounded span
    needs no cap when the ``WHERE`` clause is the bound.
    """

    _USER = "user_range_invalidate"
    _OTHER_USER = "user_range_bystander"

    async def _generated_on(self, repo, day, user=None):
        await repo.upsert(
            JournalDailySummary(
                user_id=user or self._USER,
                summary_date=day,
                summary_text=f"Summary for {day.isoformat()}.",
                status=SummaryStatus.GENERATED,
                generated_at=datetime(2026, 4, 27, 7, 0, tzinfo=UTC),
            )
        )

    async def _status_on(self, repo, day, user=None):
        row = await repo.find_by_user_and_date(user or self._USER, day)
        assert row is not None
        return row.status

    @pytest.mark.asyncio
    async def test_every_day_of_the_span_is_marked_pending(self, daily_summary_repo):
        for day in (date(2026, 4, 24), date(2026, 4, 25), date(2026, 4, 26)):
            await self._generated_on(daily_summary_repo, day)

        await daily_summary_repo.invalidate_for_range(
            self._USER, date(2026, 4, 24), date(2026, 4, 26)
        )

        for day in (date(2026, 4, 24), date(2026, 4, 25), date(2026, 4, 26)):
            assert await self._status_on(daily_summary_repo, day) == (
                SummaryStatus.PENDING
            )

    @pytest.mark.asyncio
    async def test_the_days_either_side_are_untouched(self, daily_summary_repo):
        """Both ends are inclusive, so the proof is the days just outside them."""
        for day in (date(2026, 4, 23), date(2026, 4, 24), date(2026, 4, 27)):
            await self._generated_on(daily_summary_repo, day)

        await daily_summary_repo.invalidate_for_range(
            self._USER, date(2026, 4, 24), date(2026, 4, 26)
        )

        assert await self._status_on(daily_summary_repo, date(2026, 4, 23)) == (
            SummaryStatus.GENERATED
        )
        assert await self._status_on(daily_summary_repo, date(2026, 4, 24)) == (
            SummaryStatus.PENDING
        )
        assert await self._status_on(daily_summary_repo, date(2026, 4, 27)) == (
            SummaryStatus.GENERATED
        )

    @pytest.mark.asyncio
    async def test_another_users_day_in_the_same_span_is_untouched(
        self, daily_summary_repo
    ):
        await self._generated_on(daily_summary_repo, date(2026, 4, 25))
        await self._generated_on(
            daily_summary_repo, date(2026, 4, 25), user=self._OTHER_USER
        )

        await daily_summary_repo.invalidate_for_range(
            self._USER, date(2026, 4, 24), date(2026, 4, 26)
        )

        assert (
            await self._status_on(
                daily_summary_repo, date(2026, 4, 25), user=self._OTHER_USER
            )
            == SummaryStatus.GENERATED
        )

    @pytest.mark.asyncio
    async def test_a_span_over_days_that_have_no_summary_is_a_no_op(
        self, daily_summary_repo
    ):
        """Invalidation only ever affects rows that exist — it creates none."""
        await daily_summary_repo.invalidate_for_range(
            "user_with_nothing", date(2026, 4, 1), date(2026, 12, 31)
        )

        assert (
            await daily_summary_repo.find_by_user_and_date(
                "user_with_nothing", date(2026, 4, 27)
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_a_generating_row_in_the_span_is_marked_pending(
        self, daily_summary_repo
    ):
        """The mechanism the generation race relies on: a claim can be undone."""
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=date(2026, 4, 25),
                status=SummaryStatus.GENERATING,
            )
        )

        await daily_summary_repo.invalidate_for_range(
            self._USER, date(2026, 4, 25), date(2026, 4, 25)
        )

        assert await self._status_on(daily_summary_repo, date(2026, 4, 25)) == (
            SummaryStatus.PENDING
        )

    @pytest.mark.asyncio
    async def test_a_single_day_span_is_the_narrow_method(self, daily_summary_repo):
        """``invalidate_for_date`` is this statement with both ends the same."""
        await self._generated_on(daily_summary_repo, date(2026, 4, 25))

        await daily_summary_repo.invalidate_for_date(self._USER, date(2026, 4, 25))

        assert await self._status_on(daily_summary_repo, date(2026, 4, 25)) == (
            SummaryStatus.PENDING
        )


class TestReleasingAClaimNobodyWillHonour:
    """What a discarded generation does with the claim it is abandoning.

    ``GENERATING`` is not an inert status — ``get_or_generate`` returns early on
    it — so a claim left behind strands the day. Releasing it is one guarded
    statement rather than a read followed by a write, because the gap between
    those is long enough for a concurrent run to finish the day, and resetting a
    *completed* summary would discard a good generation and pay for another.
    """

    _USER = "user_release_claim"
    _DATE = date(2026, 4, 27)

    @pytest.mark.asyncio
    async def test_a_claim_is_released_to_pending(self, daily_summary_repo):
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=self._DATE,
                summary_text="The prose the user is looking at.",
                status=SummaryStatus.GENERATING,
            )
        )

        assert await daily_summary_repo.release_claim(self._USER, self._DATE) is True

        row = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert row is not None
        assert row.status == SummaryStatus.PENDING
        assert row.summary_text == "The prose the user is looking at."

    @pytest.mark.asyncio
    async def test_a_finished_summary_is_never_released(self, daily_summary_repo):
        """The race review found: a concurrent run finished it in the meantime."""
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=self._DATE,
                summary_text="Written by the faster run.",
                status=SummaryStatus.GENERATED,
                generated_at=datetime(2026, 4, 27, 8, 0, tzinfo=UTC),
            )
        )

        assert await daily_summary_repo.release_claim(self._USER, self._DATE) is False

        row = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert row is not None
        assert row.status == SummaryStatus.GENERATED
        assert row.summary_text == "Written by the faster run."

    @pytest.mark.asyncio
    async def test_releasing_moves_the_change_stamp(self, daily_summary_repo):
        """So a request already assembling inputs can see the claim was dropped."""
        await daily_summary_repo.upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=self._DATE,
                status=SummaryStatus.GENERATING,
            )
        )
        before = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert before is not None and before.invalidated_at is None

        await daily_summary_repo.release_claim(self._USER, self._DATE)

        after = await daily_summary_repo.find_by_user_and_date(self._USER, self._DATE)
        assert after is not None
        assert after.invalidated_at is not None

    @pytest.mark.asyncio
    async def test_a_day_with_no_row_releases_nothing(self, daily_summary_repo):
        assert await daily_summary_repo.release_claim("nobody", self._DATE) is False
