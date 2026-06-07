"""Daily summary generation service — orchestrates the full pipeline.

Coordinates input assembly, eligibility checking, prompt building,
AI generation, and result persistence for journal daily summaries.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary

from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)
from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)
from app.core.journal.services.daily_summary_prompt_builder import (
    DailySummaryPromptBuilder,
)
from app.core.journal.services.daily_summary_repository import (
    JournalDailySummaryRepository,
)
from app.core.settings.models import UserSettingsRepository
from app.core.settings.timezone_utils import DEFAULT_TIMEZONE

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
        _gemini_response_override: str | None = None,
    ) -> None:
        self._input_assembler = input_assembler
        self._eligibility_checker = eligibility_checker
        self._prompt_builder = prompt_builder
        self._summary_repo = summary_repo
        self._gemini_api_key = gemini_api_key
        self._gemini_model = gemini_model
        self._user_settings_repo = user_settings_repo
        self._gemini_response_override = _gemini_response_override

    async def _resolve_timezone(self, user_id: str) -> str:
        """Resolve the user's timezone, falling back to UTC."""
        if self._user_settings_repo is None:
            return DEFAULT_TIMEZONE
        return await self._user_settings_repo.get_timezone(user_id)

    async def get_or_generate(
        self, user_id: str, summary_date: date
    ) -> JournalDailySummary | None:
        """Get a cached summary or generate a new one.

        Returns the existing summary if already GENERATED,
        otherwise assembles input and generates a new one.
        """
        if not self._gemini_api_key:
            logger.info(
                "No Gemini API key configured, skipping daily summary generation"
            )
            return None

        # 1. Check cache
        existing = await self._summary_repo.find_by_user_and_date(user_id, summary_date)
        if existing and existing.status == SummaryStatus.GENERATED:
            logger.info(
                "Returning cached daily summary for %s on %s",
                user_id,
                summary_date,
            )
            return existing

        # Skip if currently generating (prevent concurrent generation)
        if existing and existing.status == SummaryStatus.GENERATING:
            logger.info(
                "Daily summary for %s on %s is currently generating",
                user_id,
                summary_date,
            )
            return existing

        # 2. Assemble input (scoped to the user's local day)
        timezone = await self._resolve_timezone(user_id)
        summary_input = await self._input_assembler.assemble(
            user_id, summary_date, timezone
        )

        # 3. Check eligibility
        if not self._eligibility_checker.is_eligible(summary_input.journal_count):
            logger.info(
                "Day %s has %d journals, below threshold — not eligible",
                summary_date,
                summary_input.journal_count,
            )
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

        # 4. Set status GENERATING (use update_status to preserve existing fields;
        #    fall back to upsert if no row exists yet)
        updated = await self._summary_repo.update_status(
            user_id, summary_date, SummaryStatus.GENERATING.value
        )
        if updated is None:
            await self._summary_repo.upsert(
                JournalDailySummary(
                    user_id=user_id,
                    summary_date=summary_date,
                    status=SummaryStatus.GENERATING,
                )
            )

        # 5. Build prompt and call Gemini
        try:
            prompt = self._prompt_builder.build(summary_input, timezone=timezone)
            raw_response = await self._call_gemini(prompt)
            result = self._parse_response(raw_response)
        except Exception as e:
            logger.exception(
                "AI generation failed for daily summary %s on %s: %s",
                user_id,
                summary_date,
                e,
            )
            # Use update_status to preserve existing text/counts;
            # fall back to upsert if no row exists yet
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

        # 6. Persist result
        now = datetime.now(tz=UTC)
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
        return await self._summary_repo.upsert(generated_summary)

    async def regenerate(
        self, user_id: str, summary_date: date
    ) -> JournalDailySummary | None:
        """Force regenerate a daily summary by invalidating cache first."""
        await self._summary_repo.invalidate_for_date(user_id, summary_date)
        return await self.get_or_generate(user_id, summary_date)

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
        from google.genai import types

        from app.mcp.shared.read_only_tools import create_read_only_mcp_server

        read_only_mcp = await create_read_only_mcp_server(
            "Daily Summary Generation Tools"
        )

        client = genai.Client(api_key=self._gemini_api_key)

        max_attempts = 3
        base_delay = 1.0

        async with Client(read_only_mcp) as mcp_client:
            for attempt in range(max_attempts):
                try:
                    response = await client.aio.models.generate_content(
                        model=self._gemini_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            tools=[mcp_client.session],
                            temperature=0.3,
                        ),
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
