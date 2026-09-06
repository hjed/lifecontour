"""Integration tests for DailySummaryService against a real database.

Exercises the ``get_or_generate`` pipeline end-to-end through real SQL. Each
write (the ``GENERATING`` marker and the final ``GENERATED``/``FAILED`` result)
commits as its own short unit of work so no transaction is held across the AI
call (issue #970); before issue #945's fix the REST controller also left these
writes uncommitted, discarding the summary at request teardown. The AI call and
input assembly are stubbed; the repository and connection are real.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary

from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)
from app.core.journal.services.daily_summary_freshness import (
    DailySummaryFreshnessChecker,
)
from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.core.journal.services.journal_date_resolver import today_in
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.settings.timezone_utils import resolve_timezone

_USER = "user_ds_integ"
_DATE = date(2026, 4, 27)


@pytest.mark.integration
class TestDailySummaryServiceTransactionalIntegration:
    """get_or_generate / regenerate commit their writes via the service layer."""

    @pytest.fixture
    def service(self, async_connection):
        assembler = AsyncMock()
        assembler.assemble.return_value = DailySummaryInput(
            user_id=_USER,
            summary_date=_DATE,
            journals=[],
            journal_count=2,
            event_count=1,
            contact_names=["Alice"],
            mood_values=[7, 8],
        )
        eligibility = MagicMock()
        eligibility.is_eligible.return_value = True
        prompt_builder = MagicMock()
        prompt_builder.build.return_value = "prompt"
        return DailySummaryService(
            input_assembler=assembler,
            eligibility_checker=eligibility,
            prompt_builder=prompt_builder,
            summary_repo=SqlJournalDailySummaryRepository(async_connection),
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override=json.dumps({"summary_text": "A productive day."}),
        )

    @pytest.mark.asyncio
    async def test_get_or_generate_persists_generated_summary(
        self, service, async_connection
    ):
        """A freshly generated summary is durably written through real SQL."""
        result = await service.get_or_generate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED

        # Read back via a separate repo on the same connection: the final
        # result's unit of work released its savepoint, so the row is present
        # (it was not rolled back as an uncommitted write would be).
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(_USER, _DATE)
        assert persisted is not None
        assert persisted.status == SummaryStatus.GENERATED
        assert persisted.summary_text == "A productive day."

    @pytest.mark.asyncio
    async def test_marks_generating_before_calling_gemini(
        self, service, async_connection
    ):
        """The GENERATING marker commits before the AI call, holding no txn.

        Issue #970: the multi-second Gemini call must not run inside the unit of
        work. We stub ``_call_gemini`` to observe state at AI-call time: the row
        is already GENERATING (its marker committed as its own unit of work) and
        no unit of work is open on the connection (depth 0).
        """
        observed: dict[str, object] = {}

        async def fake_gemini(prompt: str) -> str:
            repo = SqlJournalDailySummaryRepository(async_connection)
            row = await repo.find_by_user_and_date(_USER, _DATE)
            observed["status"] = row.status if row else None
            observed["uow_depth"] = async_connection.info.get("uow_depth", 0)
            return json.dumps({"summary_text": "A productive day."})

        service._call_gemini = fake_gemini

        result = await service.get_or_generate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        # The marker was committed (visible on the same connection) before Gemini
        assert observed["status"] == SummaryStatus.GENERATING
        # ...and no transaction was held across the AI call.
        assert observed["uow_depth"] == 0

    @pytest.mark.asyncio
    async def test_regenerate_overwrites_existing_summary(
        self, service, async_connection
    ):
        """regenerate invalidates then re-persists as separate committed units."""
        await service.get_or_generate(_USER, _DATE, async_connection)

        result = await service.regenerate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(_USER, _DATE)
        assert persisted is not None
        assert persisted.status == SummaryStatus.GENERATED


@pytest.mark.integration
class TestDailySummaryEligibilityIntegration:
    """Today is always eligible; a past day keeps the two-journal threshold.

    The eligibility checker, the summary repository and the user-settings
    repository are all real; only input assembly and the AI call are stubbed.
    "Today" is whatever the *saved* timezone says it is, so the test never
    assumes the UTC date is the user's date — and it is derived from the same
    fixed instant the checker's clock reports, so a real midnight passing
    between the two reads cannot flip the outcome.
    """

    _USER = "user_ds_elig_integ"
    _TIMEZONE = "Pacific/Auckland"
    _NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)

    @pytest.fixture
    async def today(self, async_connection) -> date:
        settings_repo = SqlUserSettingsRepository(async_connection)
        await settings_repo.save(
            UserSettings(user_id=self._USER, timezone=self._TIMEZONE)
        )
        return today_in(resolve_timezone(self._TIMEZONE), self._NOW)

    def _service(
        self, async_connection, *, summary_date: date, journal_count: int
    ) -> DailySummaryService:
        assembler = AsyncMock()
        assembler.assemble.return_value = DailySummaryInput(
            user_id=self._USER,
            summary_date=summary_date,
            journals=[],
            journal_count=journal_count,
            event_count=0,
            contact_names=[],
            mood_values=[],
        )
        prompt_builder = MagicMock()
        prompt_builder.build.return_value = "prompt"
        return DailySummaryService(
            input_assembler=assembler,
            eligibility_checker=DailySummaryEligibilityChecker(),
            clock=lambda: self._NOW,
            prompt_builder=prompt_builder,
            summary_repo=SqlJournalDailySummaryRepository(async_connection),
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            user_settings_repo=SqlUserSettingsRepository(async_connection),
            _gemini_response_override=json.dumps({"summary_text": "A quiet day."}),
        )

    @pytest.mark.asyncio
    async def test_journal_less_today_persists_a_generated_summary(
        self, async_connection, today: date
    ):
        """A day with zero journals is a summary attempt, not a DISABLED row."""
        service = self._service(async_connection, summary_date=today, journal_count=0)

        result = await service.get_or_generate(self._USER, today, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(self._USER, today)
        assert persisted is not None
        assert persisted.status == SummaryStatus.GENERATED
        assert persisted.journal_count == 0
        assert persisted.summary_text == "A quiet day."

    @pytest.mark.asyncio
    async def test_past_day_with_one_journal_persists_disabled(
        self, async_connection, today: date
    ):
        """Below the threshold, a past day still produces no summary."""
        yesterday = today - timedelta(days=1)
        service = self._service(
            async_connection, summary_date=yesterday, journal_count=1
        )

        result = await service.get_or_generate(self._USER, yesterday, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.DISABLED
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(self._USER, yesterday)
        assert persisted is not None
        assert persisted.status == SummaryStatus.DISABLED
        assert persisted.summary_text is None


@pytest.mark.integration
class TestDailySummaryFreshnessIntegration:
    """Today's summary is regenerated on read unless it was generated today.

    Real repository, real settings repository with a saved ``Pacific/Auckland``
    timezone, and the real eligibility and freshness checkers on one fixed
    clock — 14:30 UTC on 3 September, which is 02:30 on the 4th in Auckland.
    Only the AI call is stubbed, and it counts how often it is asked.
    """

    _USER = "user_ds_fresh_integ"
    _TIMEZONE = "Pacific/Auckland"
    _NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
    # 21:00 on 3 September in Auckland (+12): last night, where the user lives.
    _LAST_NIGHT = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    # 00:30 on 4 September in Auckland: earlier this morning.
    _EARLY_TODAY = datetime(2026, 9, 3, 12, 30, tzinfo=UTC)
    _OLD_TEXT = "Written last night."
    _NEW_TEXT = "Written this morning."

    @pytest.fixture
    async def today(self, async_connection) -> date:
        settings_repo = SqlUserSettingsRepository(async_connection)
        await settings_repo.save(
            UserSettings(user_id=self._USER, timezone=self._TIMEZONE)
        )
        return today_in(resolve_timezone(self._TIMEZONE), self._NOW)

    def _service(
        self, async_connection, *, summary_date: date, ai_calls: list[str]
    ) -> DailySummaryService:
        assembler = AsyncMock()
        assembler.assemble.return_value = DailySummaryInput(
            user_id=self._USER,
            summary_date=summary_date,
            journals=[],
            journal_count=2,
            event_count=0,
            contact_names=[],
            mood_values=[],
        )
        prompt_builder = MagicMock()
        prompt_builder.build.return_value = "prompt"
        service = DailySummaryService(
            input_assembler=assembler,
            eligibility_checker=DailySummaryEligibilityChecker(),
            clock=lambda: self._NOW,
            prompt_builder=prompt_builder,
            summary_repo=SqlJournalDailySummaryRepository(async_connection),
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            user_settings_repo=SqlUserSettingsRepository(async_connection),
            freshness_checker=DailySummaryFreshnessChecker(),
        )

        async def fake_gemini(prompt: str) -> str:
            ai_calls.append(prompt)
            return json.dumps({"summary_text": self._NEW_TEXT})

        service._call_gemini = fake_gemini  # type: ignore[method-assign]
        return service

    async def _seed_generated(
        self, async_connection, summary_date: date, generated_at: datetime
    ) -> None:
        await SqlJournalDailySummaryRepository(async_connection).upsert(
            JournalDailySummary(
                user_id=self._USER,
                summary_date=summary_date,
                summary_text=self._OLD_TEXT,
                journal_count=2,
                status=SummaryStatus.GENERATED,
                generated_at=generated_at,
            )
        )

    @pytest.mark.asyncio
    async def test_a_stale_today_summary_is_regenerated_on_read(
        self, async_connection, today: date
    ):
        """Last night's summary must not be served this morning."""
        await self._seed_generated(async_connection, today, self._LAST_NIGHT)
        ai_calls: list[str] = []
        service = self._service(async_connection, summary_date=today, ai_calls=ai_calls)

        result = await service.get_or_generate(self._USER, today, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == self._NEW_TEXT
        assert len(ai_calls) == 1
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(self._USER, today)
        assert persisted is not None
        assert persisted.summary_text == self._NEW_TEXT
        assert persisted.generated_at is not None
        assert persisted.generated_at > self._LAST_NIGHT

    @pytest.mark.asyncio
    async def test_a_fresh_today_summary_is_served_from_cache(
        self, async_connection, today: date
    ):
        """Generated at 00:30 this morning: caching is unchanged."""
        await self._seed_generated(async_connection, today, self._EARLY_TODAY)
        ai_calls: list[str] = []
        service = self._service(async_connection, summary_date=today, ai_calls=ai_calls)

        result = await service.get_or_generate(self._USER, today, async_connection)

        assert result is not None
        assert result.summary_text == self._OLD_TEXT
        assert ai_calls == []
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(self._USER, today)
        assert persisted is not None
        assert persisted.summary_text == self._OLD_TEXT
        assert persisted.generated_at == self._EARLY_TODAY

    @pytest.mark.asyncio
    async def test_a_past_day_summary_is_served_from_cache(
        self, async_connection, today: date
    ):
        """Only today must reflect today; yesterday's summary is left alone."""
        yesterday = today - timedelta(days=1)
        await self._seed_generated(
            async_connection, yesterday, datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
        )
        ai_calls: list[str] = []
        service = self._service(
            async_connection, summary_date=yesterday, ai_calls=ai_calls
        )

        result = await service.get_or_generate(self._USER, yesterday, async_connection)

        assert result is not None
        assert result.summary_text == self._OLD_TEXT
        assert ai_calls == []

    @pytest.mark.asyncio
    async def test_two_stale_reads_that_both_pass_the_cache_check_generate_once(
        self, async_connection, today: date
    ):
        """The GENERATING marker is an atomic claim, so the loser calls no AI.

        The narrower race: both requests read the stale row *before* either
        marks it. Request B's claim is placed exactly there — after A's cache
        check and before A's own claim — by making it during A's input
        assembly, the one await that sits between the two. A then finds the row
        already claimed and stands down without calling the AI.
        """
        await self._seed_generated(async_connection, today, self._LAST_NIGHT)
        a_calls: list[str] = []
        a = self._service(async_connection, summary_date=today, ai_calls=a_calls)
        repo_b = SqlJournalDailySummaryRepository(async_connection)
        assembler = cast(AsyncMock, a._input_assembler)
        assembled = assembler.assemble.return_value

        async def b_claims_while_a_assembles(*args: object, **kwargs: object):
            assert (
                await repo_b.claim_for_generation(
                    self._USER, today, seen_generated_at=self._LAST_NIGHT
                )
                is True
            )
            return assembled

        assembler.assemble.side_effect = b_claims_while_a_assembles

        result = await a.get_or_generate(self._USER, today, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATING
        assert a_calls == []
        persisted = await repo_b.find_by_user_and_date(self._USER, today)
        assert persisted is not None
        assert persisted.status == SummaryStatus.GENERATING
        assert persisted.summary_text == self._OLD_TEXT

    @pytest.mark.asyncio
    async def test_a_slow_stale_read_does_not_regenerate_over_a_finished_run(
        self, async_connection, today: date
    ):
        """The widest race: B claims, generates and finishes while A is still
        between its cache check and its claim.

        A's claim carries the ``generated_at`` it saw; B's result moved it, so
        A loses, calls no AI, and returns B's fresh summary instead of writing
        its own over the top.
        """
        await self._seed_generated(async_connection, today, self._LAST_NIGHT)
        a_calls: list[str] = []
        b_calls: list[str] = []
        a = self._service(async_connection, summary_date=today, ai_calls=a_calls)
        b = self._service(async_connection, summary_date=today, ai_calls=b_calls)
        assembler = cast(AsyncMock, a._input_assembler)
        assembled = assembler.assemble.return_value

        async def b_runs_to_completion_while_a_assembles(
            *args: object, **kwargs: object
        ):
            finished = await b.get_or_generate(self._USER, today, async_connection)
            assert finished is not None
            assert finished.status == SummaryStatus.GENERATED
            return assembled

        assembler.assemble.side_effect = b_runs_to_completion_while_a_assembles

        result = await a.get_or_generate(self._USER, today, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == self._NEW_TEXT
        assert a_calls == []
        assert len(b_calls) == 1
        persisted = await SqlJournalDailySummaryRepository(
            async_connection
        ).find_by_user_and_date(self._USER, today)
        assert persisted is not None
        assert persisted.generated_at == result.generated_at

    @pytest.mark.asyncio
    async def test_concurrent_reads_of_a_stale_summary_generate_once(
        self, async_connection, today: date
    ):
        """The GENERATING guard still holds when staleness starts a regeneration.

        A second read arriving while the first is at the AI sees the committed
        GENERATING marker and waits on that run rather than starting its own.
        """
        await self._seed_generated(async_connection, today, self._LAST_NIGHT)
        first_calls: list[str] = []
        second_calls: list[str] = []
        first = self._service(
            async_connection, summary_date=today, ai_calls=first_calls
        )
        second = self._service(
            async_connection, summary_date=today, ai_calls=second_calls
        )
        observed: dict[str, object] = {}

        async def fake_gemini_with_a_concurrent_read(prompt: str) -> str:
            first_calls.append(prompt)
            concurrent = await second.get_or_generate(
                self._USER, today, async_connection
            )
            observed["status"] = concurrent.status if concurrent else None
            return json.dumps({"summary_text": self._NEW_TEXT})

        first._call_gemini = (  # type: ignore[method-assign]
            fake_gemini_with_a_concurrent_read
        )

        result = await first.get_or_generate(self._USER, today, async_connection)

        assert result is not None
        assert result.summary_text == self._NEW_TEXT
        assert observed["status"] == SummaryStatus.GENERATING
        assert len(first_calls) == 1
        assert second_calls == []


@pytest.mark.integration
class TestAnInvalidationThatLandsWhileGeneratingIsNotLost:
    """The race ITER18-005 Phase 2's review found, closed in Phase 7c.

    ``get_or_generate`` reads the row, assembles the day's inputs, then claims
    the row by compare-and-set on ``generated_at``. An invalidation landing in
    between moves the status to ``PENDING`` and leaves ``generated_at`` alone —
    so the claim still succeeds, and the finishing generation used to write
    ``GENERATED`` over the marker with a summary assembled **before** the
    change. The day then looked fresh while describing something no longer
    true, until the next input change or local midnight.

    A status guard at persist cannot close this: by then the row *is*
    ``GENERATING``, because this request claimed it. What can is a change stamp
    the invalidation moves and the persist compares — ``invalidated_at``, read
    with the row before assembly.
    """

    @pytest.fixture
    def racing_service(self, async_connection):
        """A service whose input assembly invalidates the row as it runs.

        The invalidation lands inside the window the defect lives in, which is
        the only way to exercise it: doing it before the read would be seen by
        the cache check, and after the persist would simply be the next change.
        """
        repo = SqlJournalDailySummaryRepository(async_connection)

        async def assemble_and_invalidate(*args, **kwargs) -> DailySummaryInput:
            await repo.invalidate_for_date(_USER, _DATE)
            return DailySummaryInput(
                user_id=_USER,
                summary_date=_DATE,
                journals=[],
                journal_count=2,
                event_count=1,
                contact_names=["Alice"],
                mood_values=[7, 8],
            )

        assembler = AsyncMock()
        assembler.assemble.side_effect = assemble_and_invalidate
        eligibility = MagicMock()
        eligibility.is_eligible.return_value = True
        prompt_builder = MagicMock()
        prompt_builder.build.return_value = "prompt"
        return DailySummaryService(
            input_assembler=assembler,
            eligibility_checker=eligibility,
            prompt_builder=prompt_builder,
            summary_repo=repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override=json.dumps(
                {"summary_text": "Written from inputs that are already out of date."}
            ),
        )

    async def _seed_stale(self, async_connection) -> None:
        """The state a day is actually in when this race can happen.

        ``PENDING`` with its previous prose still standing: something changed,
        the row is marked, and the next reader — this one — is about to
        regenerate it. A ``GENERATED`` row could not reach the generation path
        at all for a past day, since it would be served from cache.
        """
        repo = SqlJournalDailySummaryRepository(async_connection)
        await repo.upsert(
            JournalDailySummary(
                user_id=_USER,
                summary_date=_DATE,
                summary_text="The prose the user is looking at.",
                status=SummaryStatus.GENERATED,
                generated_at=datetime(2026, 4, 27, 7, 0, tzinfo=UTC),
            )
        )
        await repo.invalidate_for_date(_USER, _DATE)

    @pytest.mark.asyncio
    async def test_the_stale_generation_is_discarded_and_the_row_stays_pending(
        self, racing_service, async_connection
    ):
        await self._seed_stale(async_connection)

        await racing_service.get_or_generate(_USER, _DATE, async_connection)

        repo = SqlJournalDailySummaryRepository(async_connection)
        row = await repo.find_by_user_and_date(_USER, _DATE)
        assert row is not None
        assert row.status == SummaryStatus.PENDING
        assert row.summary_text != "Written from inputs that are already out of date."

    @pytest.mark.asyncio
    async def test_the_next_read_regenerates_it(self, racing_service, async_connection):
        """Which is what makes discarding the result the right answer.

        Nothing is lost by throwing the stale summary away: the ``PENDING``
        marker is exactly what the next read acts on, and that read assembles
        inputs which now include the change.
        """
        await self._seed_stale(async_connection)
        await racing_service.get_or_generate(_USER, _DATE, async_connection)

        repo = SqlJournalDailySummaryRepository(async_connection)
        service = DailySummaryService(
            input_assembler=_calm_assembler(),
            eligibility_checker=_always_eligible(),
            prompt_builder=_static_prompt(),
            summary_repo=repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override=json.dumps(
                {"summary_text": "Written from the inputs as they now are."}
            ),
        )

        result = await service.get_or_generate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "Written from the inputs as they now are."

    @pytest.mark.asyncio
    async def test_a_quiet_generation_is_written_as_before(self, async_connection):
        """The guard must not refuse the ordinary case, which is nearly all of them."""
        await self._seed_stale(async_connection)
        repo = SqlJournalDailySummaryRepository(async_connection)
        await repo.invalidate_for_date(_USER, _DATE)
        service = DailySummaryService(
            input_assembler=_calm_assembler(),
            eligibility_checker=_always_eligible(),
            prompt_builder=_static_prompt(),
            summary_repo=repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override=json.dumps({"summary_text": "All quiet."}),
        )

        result = await service.get_or_generate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "All quiet."


def _calm_assembler() -> AsyncMock:
    assembler = AsyncMock()
    assembler.assemble.return_value = DailySummaryInput(
        user_id=_USER,
        summary_date=_DATE,
        journals=[],
        journal_count=2,
        event_count=1,
        contact_names=["Alice"],
        mood_values=[7, 8],
    )
    return assembler


def _always_eligible() -> MagicMock:
    eligibility = MagicMock()
    eligibility.is_eligible.return_value = True
    return eligibility


def _static_prompt() -> MagicMock:
    prompt_builder = MagicMock()
    prompt_builder.build.return_value = "prompt"
    return prompt_builder
