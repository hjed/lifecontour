"""Unit tests for DailySummaryService."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)
from app.core.journal.services.daily_summary_freshness import (
    DailySummaryFreshnessChecker,
)
from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.journal.services.daily_summary_service import DailySummaryService

# These unit tests mock the repository, so no real connection is needed: the
# @transactional decorator no-ops for a non-AsyncConnection (the value is never
# used to commit). cast keeps the typed signature happy without a real engine.
_NO_TXN = cast(AsyncConnection, None)


@pytest.fixture
def mock_input_assembler() -> AsyncMock:
    assembler = AsyncMock()
    assembler.assemble.return_value = DailySummaryInput(
        user_id="user123",
        summary_date=date(2026, 4, 27),
        journals=[],
        journal_count=3,
        event_count=1,
        contact_names=["Alice", "Bob"],
        mood_values=[7, 8],
    )
    return assembler


@pytest.fixture
def mock_eligibility_checker() -> MagicMock:
    checker = MagicMock()
    checker.is_eligible.return_value = True
    return checker


@pytest.fixture
def mock_prompt_builder() -> MagicMock:
    builder = MagicMock()
    builder.build.return_value = "test prompt"
    return builder


@pytest.fixture
def mock_summary_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_user_and_date.return_value = None
    repo.upsert.side_effect = lambda s: s  # Return what's passed in
    # The guarded write a finished generation goes through. Returning what it
    # was given is the *accepted* case; a test exercising the refusal sets it to
    # ``None``, which is what the repository returns when the row was
    # invalidated after this run gathered its inputs.
    repo.complete_generation.side_effect = lambda s, **_: s
    repo.update_status.return_value = None  # No existing row by default
    repo.claim_for_generation.return_value = True  # This run wins the marker
    repo.invalidate_for_date.return_value = None
    repo.release_claim.return_value = True
    return repo


def _build_service(
    mock_input_assembler: AsyncMock,
    mock_eligibility_checker: MagicMock,
    mock_prompt_builder: MagicMock,
    mock_summary_repo: AsyncMock,
    *,
    gemini_api_key: str,
    response_override: str | None,
) -> DailySummaryService:
    """The service over the shared mocks, with the model configuration a test needs."""
    return DailySummaryService(
        input_assembler=mock_input_assembler,
        eligibility_checker=mock_eligibility_checker,
        prompt_builder=mock_prompt_builder,
        summary_repo=mock_summary_repo,
        gemini_api_key=gemini_api_key,
        gemini_model="gemini-2.5-pro",
        _gemini_response_override=response_override,
    )


@pytest.fixture
def service(
    mock_input_assembler: AsyncMock,
    mock_eligibility_checker: MagicMock,
    mock_prompt_builder: MagicMock,
    mock_summary_repo: AsyncMock,
) -> DailySummaryService:
    return _build_service(
        mock_input_assembler,
        mock_eligibility_checker,
        mock_prompt_builder,
        mock_summary_repo,
        gemini_api_key="test-key",
        response_override=json.dumps(
            {"summary_text": "A productive day with meetings and exercise."}
        ),
    )


@pytest.fixture
def keyless_service(
    mock_input_assembler: AsyncMock,
    mock_eligibility_checker: MagicMock,
    mock_prompt_builder: MagicMock,
    mock_summary_repo: AsyncMock,
) -> Callable[[str | None], DailySummaryService]:
    """Build a service with no Gemini key, optionally answering from an override."""

    def build(response_override: str | None) -> DailySummaryService:
        return _build_service(
            mock_input_assembler,
            mock_eligibility_checker,
            mock_prompt_builder,
            mock_summary_repo,
            gemini_api_key="",
            response_override=response_override,
        )

    return build


class TestDailySummaryServiceGeneration:
    """Test the get_or_generate pipeline."""

    @pytest.mark.asyncio
    async def test_generates_new_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
    ) -> None:
        """When no cached summary exists, generates a new one."""
        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "A productive day with meetings and exercise."
        assert result.journal_count == 3
        assert result.event_count == 1
        assert result.contact_count == 2  # Alice, Bob (deduplicated)
        assert result.mood_average == 7.5
        assert result.generated_at is not None
        mock_input_assembler.assemble.assert_called_once_with(
            "user123", date(2026, 4, 27), "UTC", now=ANY
        )
        mock_prompt_builder.build.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_cached_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When a GENERATED summary exists, returns it without regenerating."""
        cached = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Cached summary.",
            status=SummaryStatus.GENERATED,
        )
        mock_summary_repo.find_by_user_and_date.return_value = cached

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is cached
        mock_input_assembler.assemble.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_generating_summary_without_retry(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When status is GENERATING, returns it without starting a new generation."""
        generating = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.GENERATING,
        )
        mock_summary_repo.find_by_user_and_date.return_value = generating

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is generating
        mock_input_assembler.assemble.assert_not_called()

    @pytest.mark.asyncio
    async def test_regenerates_pending_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When status is PENDING, triggers regeneration."""
        pending = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.PENDING,
        )
        mock_summary_repo.find_by_user_and_date.return_value = pending
        # update_status returns the updated entity when the row exists
        mock_summary_repo.update_status.return_value = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.GENERATING,
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        mock_input_assembler.assemble.assert_called_once()

    @pytest.mark.asyncio
    async def test_regenerates_failed_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When status is FAILED, triggers regeneration."""
        failed = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.FAILED,
        )
        mock_summary_repo.find_by_user_and_date.return_value = failed
        # update_status returns the updated entity when the row exists
        mock_summary_repo.update_status.return_value = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.GENERATING,
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        mock_input_assembler.assemble.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_overwrite_concurrently_generated_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """A slower run must not overwrite a summary a faster run completed.

        The cache check passes (no row yet), but by the time this run finishes
        the AI call a concurrent request has persisted a GENERATED summary. The
        final write re-checks status and returns the existing row instead of
        clobbering it (last-writer-wins prevention).
        """
        completed = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="From the faster concurrent run.",
            status=SummaryStatus.GENERATED,
        )
        # (1) cache check: None; (2) final-write guard: the completed row.
        mock_summary_repo.find_by_user_and_date.side_effect = [None, completed]

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is completed
        # Nothing wrote a GENERATED summary (only the GENERATING marker).
        mock_summary_repo.complete_generation.assert_not_called()
        generated_upserts = [
            call
            for call in mock_summary_repo.upsert.call_args_list
            if call.args[0].status == SummaryStatus.GENERATED
        ]
        assert generated_upserts == []


class TestDailySummaryServiceEligibility:
    """Test eligibility checking."""

    @pytest.mark.asyncio
    async def test_ineligible_day_returns_disabled(
        self,
        service: DailySummaryService,
        mock_eligibility_checker: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """When the day is ineligible, returns a DISABLED summary."""
        mock_eligibility_checker.is_eligible.return_value = False

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.DISABLED
        mock_summary_repo.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_checker_receives_the_date_and_the_users_timezone(
        self,
        mock_input_assembler: AsyncMock,
        mock_eligibility_checker: MagicMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Eligibility is judged against the user's configured timezone.

        The service resolves the timezone once for input assembly; the same
        value must reach the checker, so "today" is the user's local date and
        never UTC's.
        """
        user_settings_repo = AsyncMock()
        user_settings_repo.get_timezone.return_value = "Australia/Sydney"
        service = DailySummaryService(
            input_assembler=mock_input_assembler,
            eligibility_checker=mock_eligibility_checker,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            user_settings_repo=user_settings_repo,
            _gemini_response_override=json.dumps({"summary_text": "Quiet day."}),
        )

        await service.get_or_generate("user123", date(2026, 4, 27), transaction=_NO_TXN)

        mock_eligibility_checker.is_eligible.assert_called_once_with(
            3, summary_date=date(2026, 4, 27), timezone="Australia/Sydney", now=ANY
        )


class TestDailySummaryServiceTodayIsAlwaysEligible:
    """The real checker on an injected clock, driven through the service.

    Pins the quiet-day case the dashboard headline exists for: a journal-less
    today still produces a summary *attempt*, never a DISABLED row.
    """

    _NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)

    def _service(
        self,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
        *,
        summary_date: date,
        journal_count: int,
        timezone: str,
    ) -> DailySummaryService:
        assembler = AsyncMock()
        assembler.assemble.return_value = DailySummaryInput(
            user_id="user123",
            summary_date=summary_date,
            journals=[],
            journal_count=journal_count,
            event_count=0,
            contact_names=[],
            mood_values=[],
        )
        user_settings_repo = AsyncMock()
        user_settings_repo.get_timezone.return_value = timezone
        return DailySummaryService(
            input_assembler=assembler,
            eligibility_checker=DailySummaryEligibilityChecker(),
            clock=lambda: self._NOW,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            user_settings_repo=user_settings_repo,
            _gemini_response_override=json.dumps({"summary_text": "Quiet day."}),
        )

    @pytest.mark.asyncio
    async def test_journal_less_today_is_generated_not_disabled(
        self, mock_prompt_builder: MagicMock, mock_summary_repo: AsyncMock
    ) -> None:
        """14:30 UTC is already 4 September in Sydney, so that date is today."""
        service = self._service(
            mock_prompt_builder,
            mock_summary_repo,
            summary_date=date(2026, 9, 4),
            journal_count=0,
            timezone="Australia/Sydney",
        )

        result = await service.get_or_generate(
            "user123", date(2026, 9, 4), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.journal_count == 0
        assert result.summary_text == "Quiet day."
        mock_summary_repo.claim_for_generation.assert_called_once_with(
            "user123", date(2026, 9, 4), seen_generated_at=None
        )

    @pytest.mark.asyncio
    async def test_utc_today_is_a_past_day_in_sydney_and_stays_disabled(
        self, mock_prompt_builder: MagicMock, mock_summary_repo: AsyncMock
    ) -> None:
        """UTC's 3 September is yesterday in Sydney: one journal is not enough."""
        service = self._service(
            mock_prompt_builder,
            mock_summary_repo,
            summary_date=date(2026, 9, 3),
            journal_count=1,
            timezone="Australia/Sydney",
        )

        result = await service.get_or_generate(
            "user123", date(2026, 9, 3), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.DISABLED
        mock_summary_repo.claim_for_generation.assert_not_called()
        mock_prompt_builder.build.assert_not_called()


class TestDailySummaryServiceFreshness:
    """Today's summary is served from cache only if it was generated today.

    The real freshness checker on an injected clock, driven through the
    service, for a Sydney user at 00:30 on 4 September (14:30 UTC on the 3rd).
    A summary written at 23:00 the night before is ninety minutes old and
    already stale; one written at 00:10 is fresh. Past days are never judged.
    """

    _NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
    _SYDNEY_TODAY = date(2026, 9, 4)
    _SYDNEY_YESTERDAY = date(2026, 9, 3)
    # 23:00 on 3 September in Sydney.
    _LAST_NIGHT = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)
    # 00:10 on 4 September in Sydney.
    _JUST_PAST_MIDNIGHT = datetime(2026, 9, 3, 14, 10, tzinfo=UTC)

    def _service(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
        *,
        freshness_checker: DailySummaryFreshnessChecker | MagicMock | None = None,
    ) -> DailySummaryService:
        user_settings_repo = AsyncMock()
        user_settings_repo.get_timezone.return_value = "Australia/Sydney"
        return DailySummaryService(
            input_assembler=mock_input_assembler,
            eligibility_checker=DailySummaryEligibilityChecker(),
            clock=lambda: self._NOW,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            user_settings_repo=user_settings_repo,
            freshness_checker=freshness_checker or DailySummaryFreshnessChecker(),
            _gemini_response_override=json.dumps({"summary_text": "This morning's."}),
        )

    @staticmethod
    def _generated(summary_date: date, generated_at: datetime) -> JournalDailySummary:
        return JournalDailySummary(
            user_id="user123",
            summary_date=summary_date,
            summary_text="Last night's.",
            status=SummaryStatus.GENERATED,
            generated_at=generated_at,
        )

    @pytest.mark.asyncio
    async def test_a_today_summary_generated_yesterday_is_regenerated_on_read(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        stale = self._generated(self._SYDNEY_TODAY, self._LAST_NIGHT)
        marked_generating = self._generated(self._SYDNEY_TODAY, self._LAST_NIGHT)
        marked_generating.status = SummaryStatus.GENERATING
        # Reads in order: (1) the cache check finds last night's row; (2) the
        # final write's guard re-reads and sees the GENERATING marker this run
        # committed, so it persists rather than treating it as a concurrent
        # completion.
        mock_summary_repo.find_by_user_and_date.side_effect = [
            stale,
            marked_generating,
        ]
        service = self._service(
            mock_input_assembler, mock_prompt_builder, mock_summary_repo
        )

        result = await service.get_or_generate(
            "user123", self._SYDNEY_TODAY, transaction=_NO_TXN
        )

        assert result is not None
        assert result is not stale
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "This morning's."
        mock_input_assembler.assemble.assert_called_once_with(
            "user123", self._SYDNEY_TODAY, "Australia/Sydney", now=ANY
        )
        # The existing pipeline ran: the GENERATING claim guards concurrency.
        # ...carrying the generated_at this run saw, so a run that finished in
        # between (moving it) makes this claim lose rather than overwrite.
        mock_summary_repo.claim_for_generation.assert_called_once_with(
            "user123", self._SYDNEY_TODAY, seen_generated_at=self._LAST_NIGHT
        )

    @pytest.mark.asyncio
    async def test_a_today_summary_generated_today_is_served_from_cache(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        fresh = self._generated(self._SYDNEY_TODAY, self._JUST_PAST_MIDNIGHT)
        mock_summary_repo.find_by_user_and_date.return_value = fresh
        service = self._service(
            mock_input_assembler, mock_prompt_builder, mock_summary_repo
        )

        result = await service.get_or_generate(
            "user123", self._SYDNEY_TODAY, transaction=_NO_TXN
        )

        assert result is fresh
        mock_input_assembler.assemble.assert_not_called()
        mock_summary_repo.claim_for_generation.assert_not_called()
        mock_summary_repo.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_past_day_summary_is_served_from_cache_however_old(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """UTC's 3 September is yesterday in Sydney: its summary is kept."""
        old = self._generated(
            self._SYDNEY_YESTERDAY, datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
        )
        mock_summary_repo.find_by_user_and_date.return_value = old
        service = self._service(
            mock_input_assembler, mock_prompt_builder, mock_summary_repo
        )

        result = await service.get_or_generate(
            "user123", self._SYDNEY_YESTERDAY, transaction=_NO_TXN
        )

        assert result is old
        mock_input_assembler.assemble.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_generating_today_row_is_still_left_to_the_run_that_owns_it(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """The concurrent-generation guard is unchanged by the freshness rule.

        Another request found the summary stale and is regenerating it; this
        one must wait on that run rather than start a second.
        """
        generating = self._generated(self._SYDNEY_TODAY, self._LAST_NIGHT)
        generating.status = SummaryStatus.GENERATING
        mock_summary_repo.find_by_user_and_date.return_value = generating
        service = self._service(
            mock_input_assembler, mock_prompt_builder, mock_summary_repo
        )

        result = await service.get_or_generate(
            "user123", self._SYDNEY_TODAY, transaction=_NO_TXN
        )

        assert result is generating
        mock_input_assembler.assemble.assert_not_called()
        mock_summary_repo.claim_for_generation.assert_not_called()

    @pytest.mark.asyncio
    async def test_two_stale_reads_that_both_pass_the_cache_check_generate_once(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """The marker is an atomic claim, not an unconditional write.

        Both requests read the same stale row before either marks it. The one
        that loses the claim must not call the AI: it returns the row the
        winner is regenerating, exactly as if it had seen GENERATING at the
        cache check.
        """
        stale = self._generated(self._SYDNEY_TODAY, self._LAST_NIGHT)
        claimed_by_the_other = self._generated(self._SYDNEY_TODAY, self._LAST_NIGHT)
        claimed_by_the_other.status = SummaryStatus.GENERATING
        # Reads in order: (1) the cache check finds the stale row; (2) after the
        # lost claim, the row the winner now holds.
        mock_summary_repo.find_by_user_and_date.side_effect = [
            stale,
            claimed_by_the_other,
        ]
        mock_summary_repo.claim_for_generation.return_value = False
        service = self._service(
            mock_input_assembler, mock_prompt_builder, mock_summary_repo
        )

        result = await service.get_or_generate(
            "user123", self._SYDNEY_TODAY, transaction=_NO_TXN
        )

        assert result is claimed_by_the_other
        mock_prompt_builder.build.assert_not_called()
        mock_summary_repo.upsert.assert_not_called()
        mock_summary_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_slow_stale_read_does_not_regenerate_over_a_finished_run(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """The claim carries the generated_at this run saw, so it loses to a
        run that claimed *and finished* in between — and returns that fresh
        result rather than calling the AI over it."""
        stale = self._generated(self._SYDNEY_TODAY, self._LAST_NIGHT)
        finished_by_the_other = self._generated(
            self._SYDNEY_TODAY, datetime(2026, 9, 3, 14, 20, tzinfo=UTC)
        )
        finished_by_the_other.summary_text = "The other run's."
        mock_summary_repo.find_by_user_and_date.side_effect = [
            stale,
            finished_by_the_other,
        ]
        mock_summary_repo.claim_for_generation.return_value = False
        service = self._service(
            mock_input_assembler, mock_prompt_builder, mock_summary_repo
        )

        result = await service.get_or_generate(
            "user123", self._SYDNEY_TODAY, transaction=_NO_TXN
        )

        assert result is finished_by_the_other
        mock_summary_repo.claim_for_generation.assert_called_once_with(
            "user123", self._SYDNEY_TODAY, seen_generated_at=self._LAST_NIGHT
        )
        mock_prompt_builder.build.assert_not_called()
        mock_summary_repo.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_checker_receives_the_users_timezone(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Staleness is judged in the configured zone, the same one eligibility
        and input assembly use, so the three cannot disagree about today."""
        cached = self._generated(self._SYDNEY_TODAY, self._JUST_PAST_MIDNIGHT)
        mock_summary_repo.find_by_user_and_date.return_value = cached
        freshness_checker = MagicMock()
        freshness_checker.is_stale.return_value = False
        service = self._service(
            mock_input_assembler,
            mock_prompt_builder,
            mock_summary_repo,
            freshness_checker=freshness_checker,
        )

        await service.get_or_generate(
            "user123", self._SYDNEY_TODAY, transaction=_NO_TXN
        )

        freshness_checker.is_stale.assert_called_once_with(
            cached, timezone="Australia/Sydney", now=ANY
        )

    @pytest.mark.asyncio
    async def test_only_a_generated_row_is_asked_about(
        self,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """A PENDING row regenerates on its own account; freshness is not consulted."""
        pending = self._generated(self._SYDNEY_TODAY, self._JUST_PAST_MIDNIGHT)
        pending.status = SummaryStatus.PENDING
        mock_summary_repo.find_by_user_and_date.return_value = pending
        freshness_checker = MagicMock()
        service = self._service(
            mock_input_assembler,
            mock_prompt_builder,
            mock_summary_repo,
            freshness_checker=freshness_checker,
        )

        result = await service.get_or_generate(
            "user123", self._SYDNEY_TODAY, transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        freshness_checker.is_stale.assert_not_called()


class TestDailySummaryServiceFailure:
    """Test failure handling."""

    @pytest.mark.asyncio
    async def test_gemini_failure_returns_failed(
        self,
        mock_input_assembler: AsyncMock,
        mock_eligibility_checker: MagicMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """When Gemini returns invalid JSON, the summary is set to FAILED."""
        # After upsert fallback, find_by_user_and_date is called to return the entity
        failed_entity = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.FAILED,
        )
        # Reads in order: (1) cache check returns None; (2) _mark_failed guard
        # read returns None (no concurrent success); (3) post-upsert fallback
        # read returns the upserted FAILED entity.
        mock_summary_repo.find_by_user_and_date.side_effect = [
            None,
            None,
            failed_entity,
        ]

        service = DailySummaryService(
            input_assembler=mock_input_assembler,
            eligibility_checker=mock_eligibility_checker,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override="not valid json",
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        # update_status returns None (no existing row), so upsert is used as fallback
        mock_summary_repo.update_status.assert_any_call(
            "user123", date(2026, 4, 27), "failed"
        )
        assert result is not None
        assert result.status == SummaryStatus.FAILED

    @pytest.mark.asyncio
    async def test_failed_does_not_clobber_concurrent_generated(
        self,
        mock_input_assembler: AsyncMock,
        mock_eligibility_checker: MagicMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """A failed AI call must not overwrite a summary another run completed.

        While this request's Gemini call was failing, a concurrent request
        completed the summary. The FAILED write re-checks status and returns the
        existing GENERATED row instead of flipping it to FAILED.
        """
        completed = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="From the concurrent run.",
            status=SummaryStatus.GENERATED,
        )
        # (1) cache check returns None; (2) _mark_failed guard read sees the
        # concurrently-completed GENERATED row.
        mock_summary_repo.find_by_user_and_date.side_effect = [None, completed]

        service = DailySummaryService(
            input_assembler=mock_input_assembler,
            eligibility_checker=mock_eligibility_checker,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override="not valid json",
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is completed
        # The row was never flipped to FAILED.
        for call in mock_summary_repo.update_status.call_args_list:
            assert call.args[2] != SummaryStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(
        self,
        keyless_service: Callable[[str | None], DailySummaryService],
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When no API key is configured, returns None."""
        result = await keyless_service(None).get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is None
        mock_input_assembler.assemble.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_response_override_generates_without_an_api_key(
        self,
        keyless_service: Callable[[str | None], DailySummaryService],
    ) -> None:
        """An override is a configured model: the e2e stack has no key, only it."""
        service = keyless_service(json.dumps({"summary_text": "Stubbed."}))

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "Stubbed."


class TestDailySummaryServiceRegenerate:
    """Test explicit regeneration."""

    @pytest.mark.asyncio
    async def test_regenerate_invalidates_then_generates(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """Regenerate invalidates cache then delegates to get_or_generate."""
        result = await service.regenerate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        mock_summary_repo.invalidate_for_date.assert_called_once_with(
            "user123", date(2026, 4, 27)
        )
        assert result is not None
        assert result.status == SummaryStatus.GENERATED


class TestDailySummaryServiceInvalidation:
    """Test cache invalidation."""

    @pytest.mark.asyncio
    async def test_invalidate_calls_repo(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Invalidate delegates to the repository."""
        await service.invalidate("user123", date(2026, 4, 27))

        mock_summary_repo.invalidate_for_date.assert_called_once_with(
            "user123", date(2026, 4, 27)
        )


class TestDailySummaryServiceParseResponse:
    """Test response parsing."""

    def test_parse_valid_json(self) -> None:
        """Valid JSON is parsed correctly."""
        raw = json.dumps({"summary_text": "A good day."})
        result = DailySummaryService._parse_response(raw)
        assert result["summary_text"] == "A good day."

    def test_parse_markdown_fenced_json(self) -> None:
        """JSON wrapped in markdown code fences is parsed."""
        raw = '```json\n{"summary_text": "A good day."}\n```'
        result = DailySummaryService._parse_response(raw)
        assert result["summary_text"] == "A good day."

    def test_parse_missing_summary_text(self) -> None:
        """Missing summary_text raises ValueError."""
        raw = json.dumps({"other_field": "value"})
        with pytest.raises(ValueError, match="summary_text"):
            DailySummaryService._parse_response(raw)

    def test_parse_empty_summary_text(self) -> None:
        """Empty summary_text raises ValueError."""
        raw = json.dumps({"summary_text": ""})
        with pytest.raises(ValueError, match="non-empty"):
            DailySummaryService._parse_response(raw)

    def test_parse_invalid_json(self) -> None:
        """Invalid JSON raises json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            DailySummaryService._parse_response("not json")


class TestDailySummaryServiceMoodAverage:
    """Test mood average computation."""

    def test_average_with_values(self) -> None:
        assert DailySummaryService._compute_mood_average([6, 8, 7]) == 7.0

    def test_average_with_single_value(self) -> None:
        assert DailySummaryService._compute_mood_average([5]) == 5.0

    def test_average_with_no_values(self) -> None:
        assert DailySummaryService._compute_mood_average([]) is None

    def test_average_rounding(self) -> None:
        assert DailySummaryService._compute_mood_average([7, 8]) == 7.5


class TestSanitizeSchema:
    """Test schema sanitization for google-genai bug.

    Tests the shared sanitize_schema function from app.mcp.shared.read_only_tools.
    """

    def test_sanitize_removes_boolean_additional_properties(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {
            "additionalProperties": False,
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }
        sanitize_schema(schema)
        assert "additionalProperties" not in schema
        assert schema["type"] == "object"
        assert "a" in schema["properties"]

    def test_sanitize_removes_boolean_items(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {"items": False, "type": "array"}
        sanitize_schema(schema)
        assert "items" not in schema
        assert schema["type"] == "array"

    def test_sanitize_recursively_removes_properties(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"deep": {"type": "array", "items": False}},
                }
            },
            "anyOf": [{"type": "object", "additionalProperties": False}],
        }
        sanitize_schema(schema)

        assert "additionalProperties" not in schema["properties"]["nested"]
        assert "items" not in schema["properties"]["nested"]["properties"]["deep"]
        assert "additionalProperties" not in schema["anyOf"][0]

    def test_sanitize_ignores_non_booleans(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {
            "additionalProperties": {"type": "string"},
            "items": {"type": "integer"},
        }
        sanitize_schema(schema)
        assert schema["additionalProperties"] == {"type": "string"}
        assert schema["items"] == {"type": "integer"}

    def test_sanitize_ignores_non_dicts(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        # Should not raise any exceptions
        sanitize_schema("not a dict")  # type: ignore
        sanitize_schema(None)  # type: ignore


class TestDailySummaryGeminiToolContext:
    """The Gemini call must expose the request DI container to read-only tools.

    Gemini may invoke the read-only MCP tools via automatic function calling.
    Those tools resolve ``SessionUser`` / ``AsyncConnection`` from the
    ``mcp_background_container`` contextvar. If it is not set (e.g. the REST
    controller path, which has neither a background container nor a FastMCP
    HTTP request), every tool call errors, the model returns no final text,
    and ``_parse_response("")`` fails with "Expecting value: line 1 column 1".
    """

    @pytest.mark.asyncio
    async def test_call_gemini_sets_and_resets_background_container(
        self,
        mock_input_assembler: AsyncMock,
        mock_eligibility_checker: MagicMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from contextlib import asynccontextmanager

        from app.mcp.shared import dependencies as mcp_deps

        sentinel_container = cast(Any, object())

        service = DailySummaryService(
            input_assembler=mock_input_assembler,
            eligibility_checker=mock_eligibility_checker,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-flash",
            container=sentinel_container,
        )

        # Capture what the tools would see at generate_content time.
        seen: dict[str, Any] = {}

        async def fake_generate_content(**_kwargs: Any) -> Any:
            seen["container"] = mcp_deps.mcp_background_container.get()
            resp = MagicMock()
            resp.text = json.dumps({"summary_text": "Generated."})
            return resp

        fake_client = MagicMock()
        fake_client.aio.models.generate_content = AsyncMock(
            side_effect=fake_generate_content
        )

        @asynccontextmanager
        async def fake_mcp_client(_server: Any) -> Any:
            session = MagicMock()
            holder = MagicMock()
            holder.session = session
            yield holder

        monkeypatch.setattr(
            "app.mcp.shared.read_only_tools.create_read_only_mcp_server",
            AsyncMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "app.mcp.shared.read_only_tools.build_gemini_session_config",
            lambda _session: {"tools": [_session]},
        )
        monkeypatch.setattr("fastmcp.Client", fake_mcp_client)
        monkeypatch.setattr("google.genai.Client", lambda **_kw: fake_client)

        # Precondition: nothing set before the call.
        assert mcp_deps.mcp_background_container.get() is None

        result = await service._call_gemini("prompt")

        assert json.loads(result)["summary_text"] == "Generated."
        # The tools saw the service's request container during generation.
        assert seen["container"] is sentinel_container
        # ...and it is reset afterward so nothing leaks to the next request.
        assert mcp_deps.mcp_background_container.get() is None


class TestTheDayIsResolvedFromOneInstant:
    """Assembly and prompt building must agree about which day is today.

    Each decides it for itself — the assembler whether to *gather* the agenda,
    the builder whether to *render* it — and each reads the clock only if the
    service does not hand it one. Two independent reads leave a window, narrow
    but real, in which local midnight falls between them: the assembler sees a
    day that is not yet today and gathers nothing, the builder sees one that is
    and labels the prompt accordingly, and the result is a today-prompt whose
    agenda is silently missing. Sharing one instant closes it.
    """

    @pytest.mark.asyncio
    async def test_the_assembler_and_the_prompt_builder_are_given_the_same_now(
        self,
        service: DailySummaryService,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
    ) -> None:
        await service.get_or_generate("user123", date(2026, 4, 27), AsyncMock())

        assembled_now = mock_input_assembler.assemble.call_args.kwargs["now"]
        built_now = mock_prompt_builder.build.call_args.kwargs["now"]

        assert assembled_now is not None
        assert assembled_now == built_now

    @pytest.mark.asyncio
    async def test_the_shared_instant_is_timezone_aware(
        self,
        service: DailySummaryService,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """A naive instant would be read as UTC by one side and guessed by the other."""
        await service.get_or_generate("user123", date(2026, 4, 27), AsyncMock())

        assembled_now = mock_input_assembler.assemble.call_args.kwargs["now"]

        assert assembled_now.tzinfo is not None

    @pytest.mark.asyncio
    async def test_eligibility_is_judged_against_the_same_instant(
        self,
        service: DailySummaryService,
        mock_eligibility_checker: MagicMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """Otherwise a day counted as today can be judged as yesterday.

        Eligibility is where a second clock reading costs the most: a day that
        was today when its journals were counted, judged after local midnight,
        is no longer today, falls to the journal threshold and persists a
        ``DISABLED`` row — the always-eligible rule turned off for exactly the
        day it protects.
        """
        await service.get_or_generate("user123", date(2026, 4, 27), AsyncMock())

        assembled_now = mock_input_assembler.assemble.call_args.kwargs["now"]
        judged_now = mock_eligibility_checker.is_eligible.call_args.kwargs["now"]

        assert judged_now == assembled_now

    @pytest.mark.asyncio
    async def test_freshness_is_judged_against_the_same_instant(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """Every day-based decision in one request reads one clock."""
        checker = MagicMock()
        checker.is_stale.return_value = True
        service._freshness_checker = checker  # noqa: SLF001
        mock_summary_repo.find_by_user_and_date.return_value = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Yesterday's prose.",
            status=SummaryStatus.GENERATED,
            generated_at=datetime(2026, 4, 26, 22, 0, tzinfo=UTC),
        )

        await service.get_or_generate("user123", date(2026, 4, 27), AsyncMock())

        assembled_now = mock_input_assembler.assemble.call_args.kwargs["now"]
        assert checker.is_stale.call_args.kwargs["now"] == assembled_now


class TestARefusedWriteHandsTheDayBack:
    """What the service does when the guarded write says no.

    The repository refuses to write a finished summary over a row that was
    invalidated after this run gathered its inputs. That leaves the row exactly
    as the claim left it — ``GENERATING`` — and that status is not inert:
    ``get_or_generate`` returns early on it, so leaving it there would strand
    the day behind a marker nothing clears.
    """

    @staticmethod
    def _service(
        mock_prompt_builder: MagicMock, mock_summary_repo: AsyncMock
    ) -> DailySummaryService:
        assembler = AsyncMock()
        assembler.assemble.return_value = DailySummaryInput(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            journals=[],
            journal_count=2,
            event_count=0,
            contact_names=[],
            mood_values=[],
        )
        eligibility = MagicMock()
        eligibility.is_eligible.return_value = True
        return DailySummaryService(
            input_assembler=assembler,
            eligibility_checker=eligibility,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override=json.dumps({"summary_text": "Already stale."}),
        )

    @pytest.mark.asyncio
    async def test_a_refused_write_moves_the_row_back_to_pending(
        self, mock_prompt_builder: MagicMock, mock_summary_repo: AsyncMock
    ) -> None:
        # ``side_effect`` wins over ``return_value``, so the fixture's
        # accept-everything default has to be cleared to refuse.
        mock_summary_repo.complete_generation.side_effect = None
        mock_summary_repo.complete_generation.return_value = None
        generating = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.GENERATING,
        )
        mock_summary_repo.release_claim.return_value = True
        mock_summary_repo.find_by_user_and_date.side_effect = [
            None,  # the cache check
            None,  # the concurrent-completion re-read
            generating,  # what it hands back after releasing the claim
        ]

        await self._service(mock_prompt_builder, mock_summary_repo).get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        # One guarded statement, not a read followed by a write: the gap
        # between those is long enough for a concurrent run to finish the day,
        # and this must never reset a completed summary.
        mock_summary_repo.release_claim.assert_awaited_once_with(
            "user123", date(2026, 4, 27)
        )
        mock_summary_repo.invalidate_for_date.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_concurrently_finished_summary_is_left_alone(
        self, mock_prompt_builder: MagicMock, mock_summary_repo: AsyncMock
    ) -> None:
        """The other reason a write is refused, and it must not be undone.

        If a faster run completed the day between this one's re-read and its
        write, the row is ``GENERATED`` and good. Marking it stale would discard
        a perfectly current summary and pay for another.
        """
        # ``side_effect`` wins over ``return_value``, so the fixture's
        # accept-everything default has to be cleared to refuse.
        mock_summary_repo.complete_generation.side_effect = None
        mock_summary_repo.complete_generation.return_value = None
        completed = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Written by the faster run.",
            status=SummaryStatus.GENERATED,
        )
        # The guarded release finds no GENERATING row and changes nothing.
        mock_summary_repo.release_claim.return_value = False
        mock_summary_repo.find_by_user_and_date.side_effect = [None, None, completed]

        result = await self._service(
            mock_prompt_builder, mock_summary_repo
        ).get_or_generate("user123", date(2026, 4, 27), transaction=_NO_TXN)

        assert result is completed
        # The release is refused by its own guard rather than skipped by a
        # status check here, so calling it is correct and harmless.
        assert mock_summary_repo.release_claim.await_count == 1

    @pytest.mark.asyncio
    async def test_the_stamp_the_write_is_guarded_on_is_read_before_assembly(
        self, mock_prompt_builder: MagicMock, mock_summary_repo: AsyncMock
    ) -> None:
        """Which is what makes the guard cover the window the defect lives in.

        The claim compares ``generated_at``, and an invalidation does not move
        that — so an input change landing between the read and the claim still
        wins its claim. Comparing the stamp as it was **before** the inputs were
        gathered is what catches it.
        """
        stamped = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.PENDING,
            invalidated_at=datetime(2026, 4, 27, 6, 0, tzinfo=UTC),
        )
        mock_summary_repo.find_by_user_and_date.return_value = stamped

        await self._service(mock_prompt_builder, mock_summary_repo).get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        _, kwargs = mock_summary_repo.complete_generation.call_args
        assert kwargs["seen_invalidated_at"] == datetime(2026, 4, 27, 6, 0, tzinfo=UTC)
