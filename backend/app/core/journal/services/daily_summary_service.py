"""Daily summary generation service — orchestrates the full pipeline.

Coordinates input assembly, eligibility checking, prompt building,
AI generation, and result persistence for journal daily summaries.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)
from app.core.journal.services.daily_summary_freshness import (
    DailySummaryFreshnessChecker,
)
from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)
from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.journal.services.daily_summary_prompt_builder import (
    DailySummaryPromptBuilder,
)
from app.core.journal.services.daily_summary_repository import (
    JournalDailySummaryRepository,
)
from app.core.settings.models import UserSettingsRepository
from app.core.settings.timezone_utils import DEFAULT_TIMEZONE
from app.infrastructure.unit_of_work import transactional

if TYPE_CHECKING:
    from dishka import AsyncContainer

logger = logging.getLogger(__name__)


class DailySummaryService:
    """Orchestrates the full AI daily summary generation pipeline."""

    def __init__(
        self,
        input_assembler: DailySummaryInputAssembler,
        eligibility_checker: DailySummaryEligibilityChecker,
        prompt_builder: DailySummaryPromptBuilder,
        summary_repo: JournalDailySummaryRepository,
        gemini_api_key: str,
        gemini_model: str,
        user_settings_repo: UserSettingsRepository | None = None,
        container: AsyncContainer | None = None,
        freshness_checker: DailySummaryFreshnessChecker | None = None,
        clock: Callable[[], datetime] | None = None,
        _gemini_response_override: str | None = None,
    ) -> None:
        self._input_assembler = input_assembler
        self._eligibility_checker = eligibility_checker
        self._freshness_checker = (
            freshness_checker
            if freshness_checker is not None
            else DailySummaryFreshnessChecker()
        )
        self._prompt_builder = prompt_builder
        self._summary_repo = summary_repo
        self._gemini_api_key = gemini_api_key
        self._gemini_model = gemini_model
        self._user_settings_repo = user_settings_repo
        self._container = container
        # The request's instant. It lives here rather than on each collaborator
        # because the request is what "now" belongs to: the checkers keep their
        # own clocks for callers that have none, but a run through this service
        # imposes one reading on all of them, so pinning the local-midnight
        # boundary in a test means pinning it once, here.
        self._clock = clock if clock is not None else _utc_now
        self._gemini_response_override = _gemini_response_override

    async def _resolve_timezone(self, user_id: str) -> str:
        """Resolve the user's timezone, falling back to UTC."""
        if self._user_settings_repo is None:
            return DEFAULT_TIMEZONE
        return await self._user_settings_repo.get_timezone(user_id)

    async def get_or_generate(
        self, user_id: str, summary_date: date, transaction: AsyncConnection
    ) -> JournalDailySummary | None:
        """Get a cached summary or generate a new one.

        Returns the existing summary if already GENERATED **and fresh**,
        otherwise assembles input and generates a new one. Freshness is the
        specification's rule that today's summary must reflect today: a
        summary for today that was not generated today in the user's timezone
        is regenerated on read, so one produced yesterday evening is never
        served this morning. Any other day's summary is served from cache
        however old it is. The rule lives here rather than at either surface so
        REST and MCP inherit it without logic of their own.

        This orchestrator deliberately holds **no** transaction across the
        multi-second Gemini call (issue #970). Each write commits as its own
        short unit of work via a ``@transactional`` helper: the ``GENERATING``
        marker is committed *before* the AI call (so concurrent callers see it
        and the row lock is released), then the AI call runs with no transaction
        held, then the ``GENERATED``/``FAILED`` result is committed afterwards —
        re-checking status first so a slower run can't overwrite a summary
        another request already completed (last-writer-wins prevention).

        The marker is an atomic **claim**, not an unconditional write: two
        requests that both pass the cache check before either marks the row
        (two stale reads at 07:00, or two reads of an invalidated row) race for
        it, exactly one wins, and the loser returns the row the winner is
        regenerating — or has already regenerated — without calling the AI. The
        claim is keyed on the ``generated_at`` the cache check saw, so a slow
        request cannot regenerate over a result a faster one finished meanwhile.

        Committing in the service layer (rather than relying on teardown) is
        required because the request connection has no commit backstop, so an
        uncommitted write would be discarded at teardown (issue #945).
        """
        # A response override is a configured model too: it is how the e2e
        # stack (ENABLE_TEST_DAILY_SUMMARY_STUB) and the tests generate without
        # a key.
        if not self._gemini_api_key and self._gemini_response_override is None:
            logger.info(
                "No Gemini API key configured, skipping daily summary generation"
            )
            return None

        # The user's zone anchors every day-based decision below: freshness,
        # input assembly and eligibility all read "today" from it.
        timezone = await self._resolve_timezone(user_id)

        # And the *instant* is read once, then imposed on every collaborator
        # that asks what day it is: freshness, assembly, eligibility and the
        # prompt. Each can read its own clock and does when called from
        # elsewhere, but four readings inside one request is four chances to
        # straddle local midnight, and each straddle has its own symptom — a
        # today-prompt whose agenda is silently missing, or, worse, a day that
        # was today when its journals were counted being judged as yesterday
        # and persisted DISABLED against the always-eligible rule. One reading
        # cannot disagree with itself.
        now = self._clock()

        # 1. Check cache (read — no transaction held). A GENERATED row is
        #    served unless it is today's and was not generated today, in which
        #    case it falls through to the same generate path an invalidated
        #    (PENDING) row takes — so the GENERATING guard below still holds.
        existing = await self._summary_repo.find_by_user_and_date(user_id, summary_date)
        if existing and existing.status == SummaryStatus.GENERATED:
            if not self._freshness_checker.is_stale(
                existing, timezone=timezone, now=now
            ):
                logger.info(
                    "Returning cached daily summary for %s on %s",
                    user_id,
                    summary_date,
                )
                return existing
            logger.info(
                "Daily summary for %s on %s was not generated today; regenerating",
                user_id,
                summary_date,
            )

        # Skip if currently generating (prevent concurrent generation)
        if existing and existing.status == SummaryStatus.GENERATING:
            logger.info(
                "Daily summary for %s on %s is currently generating",
                user_id,
                summary_date,
            )
            return existing

        # The change stamp as it stands **before** the inputs are gathered.
        # Anything that invalidates this day from here on moves it, and the
        # persist step below refuses to write over a summary of inputs that
        # have since changed. Read here rather than at the claim because the
        # window the defect lives in opens with the assembly: the claim
        # compares ``generated_at``, which an invalidation does not move.
        #
        # **The guard is inert for a day that has no row yet**, and that is a
        # known residual rather than an oversight (raised by review). An
        # invalidation only ever marks rows that exist — it deliberately creates
        # none, since a summary nobody has read should not be manufactured — so
        # a change landing while the *first* summary for a day is being
        # generated leaves no trace for this comparison to find. Closing it
        # means either creating rows on invalidation, which trades this for a
        # table of summaries for days no one opened, or claiming the row before
        # assembling the inputs, which would hold a GENERATING marker across the
        # eligibility decision and mark days that turn out to be ineligible.
        # Both are behaviour changes beyond this phase; the case is recorded in
        # ITER18-005 Phase 7's limitations instead.
        seen_invalidated_at = existing.invalidated_at if existing else None

        # 2. Assemble input (scoped to the user's local day — reads only)
        summary_input = await self._input_assembler.assemble(
            user_id, summary_date, timezone, now=now
        )

        # 3. Check eligibility. Today (in the user's timezone) is always
        #    eligible; a past or future day needs the journal threshold.
        if not self._eligibility_checker.is_eligible(
            summary_input.journal_count,
            summary_date=summary_date,
            timezone=timezone,
            now=now,
        ):
            logger.info(
                "Day %s has %d journals, below threshold — not eligible",
                summary_date,
                summary_input.journal_count,
            )
            return await self._persist_disabled(
                user_id, summary_date, summary_input, transaction
            )

        # 4. Claim the GENERATING marker as its own short unit of work, so
        #    concurrent callers see it and the row lock is released before the
        #    AI call. The claim carries the generated_at the cache check saw:
        #    losing it means another request got here between then and now —
        #    and may already have finished — so leave the generation to it and
        #    hand back whatever it has produced.
        seen_generated_at = existing.generated_at if existing else None
        if not await self._claim_generation(
            user_id, summary_date, seen_generated_at, transaction
        ):
            logger.info(
                "Daily summary for %s on %s was claimed by a concurrent request",
                user_id,
                summary_date,
            )
            return await self._summary_repo.find_by_user_and_date(user_id, summary_date)

        # 5. Build prompt and call Gemini — with NO transaction held.
        try:
            prompt = self._prompt_builder.build(
                summary_input, now=now, timezone=timezone
            )
            raw_response = await self._call_gemini(prompt)
            result = self._parse_response(raw_response)
        except Exception as e:
            logger.exception(
                "AI generation failed for daily summary %s on %s: %s",
                user_id,
                summary_date,
                e,
            )
            return await self._mark_failed(user_id, summary_date, transaction)

        # 6. Persist the result as its own unit of work, refusing to write over
        #    an invalidation that landed while this request was working. The
        #    marker it left is what the next read acts on.
        return await self._persist_generated(
            user_id,
            summary_date,
            summary_input,
            result,
            transaction,
            seen_invalidated_at=seen_invalidated_at,
        )

    @transactional
    async def _persist_disabled(
        self,
        user_id: str,
        summary_date: date,
        summary_input: DailySummaryInput,
        transaction: AsyncConnection,
    ) -> JournalDailySummary:
        """Persist a DISABLED summary for an ineligible day (own unit of work).

        Only a past or future day can reach here — today is always eligible.
        """
        disabled_summary = JournalDailySummary(
            user_id=user_id,
            summary_date=summary_date,
            journal_count=summary_input.journal_count,
            event_count=summary_input.event_count,
            contact_count=len(set(summary_input.contact_names)),
            mood_average=self._compute_mood_average(summary_input.mood_values),
            status=SummaryStatus.DISABLED,
        )
        return await self._summary_repo.upsert(disabled_summary)

    @transactional
    async def _claim_generation(
        self,
        user_id: str,
        summary_date: date,
        seen_generated_at: datetime | None,
        transaction: AsyncConnection,
    ) -> bool:
        """Commit the GENERATING claim as its own unit of work.

        Returns whether this run won it. The repository's claim is one atomic
        compare-and-set on ``generated_at`` that creates the row if needed and
        otherwise moves only the status, so a previous generation's text and
        counters survive until the new result replaces them.
        """
        return await self._summary_repo.claim_for_generation(
            user_id, summary_date, seen_generated_at=seen_generated_at
        )

    @transactional
    async def _persist_generated(
        self,
        user_id: str,
        summary_date: date,
        summary_input: DailySummaryInput,
        result: dict[str, Any],
        transaction: AsyncConnection,
        *,
        seen_invalidated_at: datetime | None = None,
    ) -> JournalDailySummary | None:
        """Commit the GENERATED result, unless the day changed while it ran.

        Two things can have happened since this request claimed the row, and
        they need different answers.

        A **faster concurrent run** may have finished the same summary: return
        its result rather than clobbering it (last-writer-wins), which is what
        the re-read below is for.

        An **input change** may have landed — a journal edited, a task ticked, a
        date added — leaving a ``PENDING`` marker on the row. The summary in
        hand describes the day as it was *before* that change, so writing it
        would replace a marker that says "regenerate me" with prose that is
        already wrong, and the day would look fresh until the next change or
        local midnight. ``complete_generation`` refuses that write by comparing
        ``invalidated_at`` against what this request saw before it assembled its
        inputs; the row is left ``PENDING`` and the next read regenerates.
        """
        existing = await self._summary_repo.find_by_user_and_date(user_id, summary_date)
        if existing and existing.status == SummaryStatus.GENERATED:
            logger.info(
                "Daily summary for %s on %s was completed concurrently; "
                "not overwriting",
                user_id,
                summary_date,
            )
            return existing

        now = self._clock()
        generated_summary = JournalDailySummary(
            user_id=user_id,
            summary_date=summary_date,
            summary_text=result["summary_text"],
            journal_count=summary_input.journal_count,
            event_count=summary_input.event_count,
            contact_count=len(set(summary_input.contact_names)),
            mood_average=self._compute_mood_average(summary_input.mood_values),
            status=SummaryStatus.GENERATED,
            generated_at=now,
        )
        written = await self._summary_repo.complete_generation(
            generated_summary, seen_invalidated_at=seen_invalidated_at
        )
        if written is not None:
            return written

        logger.info(
            "Daily summary for %s on %s was invalidated while generating; "
            "discarding the result and leaving it to the next read",
            user_id,
            summary_date,
        )
        return await self._release_refused_claim(user_id, summary_date)

    async def _release_refused_claim(
        self, user_id: str, summary_date: date
    ) -> JournalDailySummary | None:
        """Hand a discarded generation's day back to the next read.

        The refused write leaves the row exactly as the claim left it —
        ``GENERATING`` — and that status is *not* inert: ``get_or_generate``
        returns early on it, so leaving it there would strand the day behind a
        marker nothing clears. Moving it back to ``PENDING`` is what the phase's
        criterion asks for in as many words, and is what makes the next read
        regenerate.

        **Only a claim, and the check is the statement itself.** A refusal can
        also mean a concurrent run *finished* the summary between the re-read
        above and the write, and marking that fresh result stale would throw
        away a good generation and pay for another. Reading the status here and
        writing in a second statement would leave exactly that gap open, so the
        release is one guarded ``UPDATE`` instead — raised by review on the
        first cut, which did read-then-write.
        """
        await self._summary_repo.release_claim(user_id, summary_date)
        return await self._summary_repo.find_by_user_and_date(user_id, summary_date)

    @transactional
    async def _mark_failed(
        self, user_id: str, summary_date: date, transaction: AsyncConnection
    ) -> JournalDailySummary | None:
        """Commit the FAILED status, guarding against a concurrent success.

        Re-reads the row first: if a concurrent run already completed the
        summary, return it rather than flipping a GENERATED row to FAILED.
        """
        existing = await self._summary_repo.find_by_user_and_date(user_id, summary_date)
        if existing and existing.status == SummaryStatus.GENERATED:
            logger.info(
                "Daily summary for %s on %s was completed concurrently; "
                "not marking failed",
                user_id,
                summary_date,
            )
            return existing

        # Use update_status to preserve existing text/counts;
        # fall back to upsert if no row exists yet.
        updated = await self._summary_repo.update_status(
            user_id, summary_date, SummaryStatus.FAILED.value
        )
        if updated is None:
            await self._summary_repo.upsert(
                JournalDailySummary(
                    user_id=user_id,
                    summary_date=summary_date,
                    status=SummaryStatus.FAILED,
                )
            )
            updated = await self._summary_repo.find_by_user_and_date(
                user_id, summary_date
            )
        return updated

    async def regenerate(
        self, user_id: str, summary_date: date, transaction: AsyncConnection
    ) -> JournalDailySummary | None:
        """Force regenerate a daily summary by invalidating cache first.

        The invalidation commits as its own unit of work, then ``get_or_generate``
        runs its own short units of work — no transaction is held across the AI
        call (issue #970).
        """
        await self._invalidate_committed(user_id, summary_date, transaction)
        return await self.get_or_generate(user_id, summary_date, transaction)

    @transactional
    async def _invalidate_committed(
        self, user_id: str, summary_date: date, transaction: AsyncConnection
    ) -> None:
        """Invalidate the cached summary, committed as its own unit of work."""
        await self._summary_repo.invalidate_for_date(user_id, summary_date)

    async def invalidate(self, user_id: str, summary_date: date) -> None:
        """Invalidate (set to PENDING) an existing daily summary.

        Called by the outbox processor when journals on the date change.
        """
        await self._summary_repo.invalidate_for_date(user_id, summary_date)
        logger.info("Invalidated daily summary for %s on %s", user_id, summary_date)

    async def _call_gemini(self, prompt: str) -> str:
        """Call the Gemini API or use test override."""
        if self._gemini_response_override is not None:
            return self._gemini_response_override

        import asyncio

        from fastmcp import Client
        from google import genai

        from app.mcp.shared.dependencies import mcp_background_container
        from app.mcp.shared.read_only_tools import (
            build_gemini_session_config,
            create_read_only_mcp_server,
        )

        read_only_mcp = await create_read_only_mcp_server(
            "Daily Summary Generation Tools"
        )

        client = genai.Client(api_key=self._gemini_api_key)

        max_attempts = 3
        base_delay = 1.0

        # Expose the request-scoped DI container to the read-only MCP tools that
        # Gemini may invoke via automatic function calling. Those tools resolve
        # SessionUser / AsyncConnection from this contextvar; without it (the
        # REST controller path has neither a background container nor a FastMCP
        # HTTP request) every tool call errors, the model returns no final text,
        # and _parse_response("") fails. Mirrors SummaryConsumer's setup.
        token = (
            mcp_background_container.set(self._container)
            if self._container is not None
            else None
        )
        try:
            async with Client(read_only_mcp) as mcp_client:
                config = build_gemini_session_config(mcp_client.session)
                for attempt in range(max_attempts):
                    try:
                        response = await client.aio.models.generate_content(
                            model=self._gemini_model,
                            contents=prompt,
                            config=config,
                        )
                        return response.text or ""
                    except Exception as e:
                        if attempt == max_attempts - 1:
                            raise
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "Gemini API error (attempt %d/%d), retrying in %.1fs: %s",
                            attempt + 1,
                            max_attempts,
                            delay,
                            e,
                        )
                        await asyncio.sleep(delay)

                raise RuntimeError("Unreachable")
        finally:
            if token is not None:
                mcp_background_container.reset(token)

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        """Parse AI response JSON.

        Raises ValueError on malformed JSON or missing required fields.
        """
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        parsed = json.loads(cleaned)

        if "summary_text" not in parsed:
            raise ValueError("AI response missing 'summary_text' field")

        summary_text = parsed["summary_text"]
        if not isinstance(summary_text, str) or not summary_text.strip():
            raise ValueError("AI response 'summary_text' must be a non-empty string")

        return {"summary_text": parsed["summary_text"]}

    @staticmethod
    def _compute_mood_average(mood_values: list[int]) -> float | None:
        """Compute mood average, or None if no values."""
        if not mood_values:
            return None
        return round(sum(mood_values) / len(mood_values), 1)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)
