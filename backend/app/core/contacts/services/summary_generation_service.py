"""Summary generation service — input assembly, activity checking, and AI generation.

This module provides the core business logic for AI-generated contact summaries:
- SummaryInputAssembler: gathers bounded recent activity for a contact
- LowActivityChecker: determines if a contact has insufficient activity
- SummaryGenerator: orchestrates the full generation pipeline
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core_shared.models.contacts.entities import (
    ContactSummary,
    SummaryStatus,
)

from app.core.contacts.models.repositories import (
    ContactFieldHistoryRepository,
    ContactRepository,
    ContactSummaryRepository,
)
from app.core.contacts.services.summary_models import (
    ActivityStatsBucket,
    SummaryInput,
)
from app.core.journal.models.repositories import (
    JournalContactRelationshipRepository,
    JournalRepository,
)

if TYPE_CHECKING:
    from app.core.contacts.services.summary_prompt_builder import (
        SummaryPromptBuilder,
    )

logger = logging.getLogger(__name__)


# Re-export for backward compat
__all__ = [
    "ActivityStatsBucket",
    "SummaryInput",
    "SummaryInputAssembler",
    "LowActivityChecker",
    "SummaryGenerator",
]


# ---------------------------------------------------------------------------
# SummaryInputAssembler
# ---------------------------------------------------------------------------


class SummaryInputAssembler:
    """Gathers bounded recent activity from repositories for AI input."""

    HISTORY_WINDOW_DAYS = 90
    MAX_JOURNALS = 10
    MAX_NOTES = 10
    MAX_HISTORY_ENTRIES = 20

    def __init__(
        self,
        contact_repo: ContactRepository,
        history_repo: ContactFieldHistoryRepository,
        journal_relationship_repo: JournalContactRelationshipRepository,
        journal_repo: JournalRepository,
        summary_repo: ContactSummaryRepository,
    ) -> None:
        self._contact_repo = contact_repo
        self._history_repo = history_repo
        self._journal_relationship_repo = journal_relationship_repo
        self._journal_repo = journal_repo
        self._summary_repo = summary_repo

    async def assemble(self, contact_id: int) -> SummaryInput | None:
        """Assemble bounded input data for summary generation.

        Returns None if the contact does not exist.
        """
        contact = await self._contact_repo.find_by_id(contact_id)
        if contact is None:
            return None

        # Contact metadata
        contact_name = (
            contact.get_full_name()
            if hasattr(contact, "get_full_name")
            else contact.first_name
        )
        company = getattr(contact, "company", None)
        job_title = getattr(contact, "job_title", None)

        # Recent notes (bounded)
        notes = getattr(contact, "notes", None) or []
        recent_notes = [n.content for n in notes[: self.MAX_NOTES]]

        # Relationships
        rels = getattr(contact, "relationships", None) or []
        relationships = []
        for r in rels:
            target = getattr(r, "to_contact_name", None) or "Unknown"
            rel_type = (
                str(r.relationship_type.value)
                if hasattr(r.relationship_type, "value")
                else str(r.relationship_type)
            )
            if getattr(r, "to_user", False):
                relationships.append(f"{rel_type} (to user)")
            else:
                relationships.append(f"{rel_type}: {target}")

        # Important dates
        dates = getattr(contact, "important_dates", None) or []
        important_dates = []
        for d in dates:
            dt_str = (
                str(d.date_type.value)
                if hasattr(d.date_type, "value")
                else str(d.date_type)
            )
            parts = [dt_str.replace("_", " ").title()]
            if getattr(d, "month", None):
                parts.append(f"month={d.month}")
            if getattr(d, "day", None):
                parts.append(f"day={d.day}")
            if getattr(d, "year", None):
                parts.append(f"year={d.year}")
            important_dates.append(": ".join(parts[:2]) if len(parts) > 1 else parts[0])

        # Recent field history (bounded)
        history_entries = await self._history_repo.get_contact_history(
            contact_id, limit=self.MAX_HISTORY_ENTRIES
        )
        recent_history = []
        for h in history_entries[: self.MAX_HISTORY_ENTRIES]:
            recent_history.append(
                f"Changed {h.field_name}: {h.old_value!r} → {h.new_value!r}"
            )

        # Journal relationships → fetch linked journals
        all_j_rels = await self._journal_relationship_repo.get_by_contact(contact_id)

        now = datetime.now(tz=UTC)
        window_start = now - timedelta(days=self.HISTORY_WINDOW_DAYS)

        # Split into recent and older for stats
        recent_j_rels: list[Any] = []
        older_j_rels: list[Any] = []
        for jr in all_j_rels:
            created = getattr(jr, "created_at", None)
            if created and created >= window_start:
                recent_j_rels.append(jr)
            else:
                older_j_rels.append(jr)

        # Fetch recent journals (bounded)
        recent_journals: list[dict[str, str]] = []
        for jr in recent_j_rels[: self.MAX_JOURNALS]:
            journal = await self._journal_repo.find_by_id(jr.journal_id)
            if journal:
                journal_date = ""
                if hasattr(journal, "event_date_range") and journal.event_date_range:
                    start = getattr(journal.event_date_range, "start", None)
                    if start:
                        journal_date = (
                            start.isoformat()
                            if hasattr(start, "isoformat")
                            else str(start)
                        )
                recent_journals.append(
                    {
                        "title": getattr(journal, "title", ""),
                        "content": getattr(journal, "content", ""),
                        "date": journal_date,
                    }
                )

        # Compute long-term activity statistics
        activity_stats = self._compute_activity_stats(older_j_rels, now)

        # Previous summary (for incremental generation)
        existing_summary = await self._summary_repo.find_by_contact_id(contact_id)
        previous_summary: str | None = None
        if existing_summary and existing_summary.status == SummaryStatus.GENERATED:
            previous_summary = existing_summary.summary_text

        return SummaryInput(
            contact_id=contact_id,
            contact_name=contact_name,
            company=company,
            job_title=job_title,
            recent_notes=recent_notes,
            recent_journals=recent_journals,
            relationships=relationships,
            recent_history=recent_history,
            important_dates=important_dates,
            previous_summary=previous_summary,
            activity_stats=activity_stats,
        )

    def _compute_activity_stats(
        self,
        older_journal_rels: list[Any],
        now: datetime,
    ) -> list[ActivityStatsBucket]:
        """Compute activity count buckets beyond the detail window.

        Buckets are 12-month periods starting from the end of the detail window.
        """
        if not older_journal_rels:
            return []

        window_end = now - timedelta(days=self.HISTORY_WINDOW_DAYS)

        # Determine the earliest interaction
        earliest = min(
            (getattr(jr, "created_at", window_end) for jr in older_journal_rels),
            default=window_end,
        )

        buckets: list[ActivityStatsBucket] = []
        bucket_start = window_end
        bucket_months = 12

        while bucket_start > earliest:
            bucket_end = bucket_start
            bucket_start_date = bucket_end - timedelta(days=365)

            count = sum(
                1
                for jr in older_journal_rels
                if (created := getattr(jr, "created_at", None))
                and bucket_start_date <= created < bucket_end
            )

            if count > 0:
                # Compute offset from now in months for labelling
                months_ago_end = int((now - bucket_end).days / 30)
                months_ago_start = months_ago_end + bucket_months
                label = f"{months_ago_end}-{months_ago_start} months ago"
                buckets.append(
                    ActivityStatsBucket(period_label=label, event_count=count)
                )

            bucket_start = bucket_start_date

        return buckets


# ---------------------------------------------------------------------------
# LowActivityChecker
# ---------------------------------------------------------------------------


class LowActivityChecker:
    """Determines if a contact has too little activity for summary generation."""

    DEFAULT_MIN_ACTIVITY_THRESHOLD = 2

    def __init__(self, min_activity_threshold: int | None = None) -> None:
        self._threshold = (
            min_activity_threshold
            if min_activity_threshold is not None
            else self.DEFAULT_MIN_ACTIVITY_THRESHOLD
        )

    def should_auto_disable(
        self,
        summary_input: SummaryInput,
        existing_summary: ContactSummary | None,
    ) -> bool:
        """Check if a contact should be auto-disabled due to low activity.

        Returns True if the contact should be disabled.
        Never returns True when the user has set an override.
        """
        # Never auto-disable if user has explicitly overridden
        if existing_summary and existing_summary.is_user_override:
            return False

        # Count total recent interactions
        total = (
            len(summary_input.recent_notes)
            + len(summary_input.recent_journals)
            + len(summary_input.recent_history)
        )

        return total < self._threshold


# ---------------------------------------------------------------------------
# SummaryGenerator
# ---------------------------------------------------------------------------


class SummaryGenerator:
    """Orchestrates the full AI summary generation pipeline."""

    def __init__(
        self,
        input_assembler: SummaryInputAssembler,
        activity_checker: LowActivityChecker,
        prompt_builder: SummaryPromptBuilder,
        summary_repo: ContactSummaryRepository,
        gemini_api_key: str,
        gemini_model: str,
        _gemini_response_override: str | None = None,
    ) -> None:
        self._input_assembler = input_assembler
        self._activity_checker = activity_checker
        self._prompt_builder = prompt_builder
        self._summary_repo = summary_repo
        self._gemini_api_key = gemini_api_key
        self._gemini_model = gemini_model
        self._gemini_response_override = _gemini_response_override

    async def generate(self, contact_id: int) -> ContactSummary | None:
        """Generate or regenerate an AI summary for a contact.

        Returns the resulting ContactSummary, or None if generation was skipped.
        """
        if not self._gemini_api_key:
            logger.info("No Gemini API key configured, skipping summary generation")
            return None

        # Check existing summary state
        existing = await self._summary_repo.find_by_contact_id(contact_id)

        # Skip if already disabled and not user-overridden
        if existing and existing.is_disabled and not existing.is_user_override:
            logger.info(
                "Contact %d summary is disabled, skipping generation",
                contact_id,
            )
            return existing

        # Set status to GENERATING
        await self._summary_repo.update_status(
            contact_id, SummaryStatus.GENERATING.value
        )

        # Assemble input
        summary_input = await self._input_assembler.assemble(contact_id)
        if summary_input is None:
            logger.warning("Contact %d not found, cannot generate summary", contact_id)
            return None

        # Check low activity
        if self._activity_checker.should_auto_disable(summary_input, existing):
            logger.info(
                "Contact %d has low activity, auto-disabling summary",
                contact_id,
            )
            disabled_summary = ContactSummary(
                contact_id=contact_id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
            )
            return await self._summary_repo.upsert(disabled_summary)

        # Build prompt
        prompt = self._prompt_builder.build(summary_input)

        # Call AI
        try:
            raw_response = await self._call_gemini(prompt)
            result = self._parse_response(raw_response)
        except Exception:
            logger.exception("AI generation failed for contact %d", contact_id)
            failed_summary = ContactSummary(
                contact_id=contact_id,
                status=SummaryStatus.FAILED,
            )
            return await self._summary_repo.upsert(failed_summary)

        # Persist result
        now = datetime.now(tz=UTC)
        generated_summary = ContactSummary(
            contact_id=contact_id,
            summary_text=result["summary_text"],
            follow_up_suggestions=result.get("follow_up_suggestions", []),
            status=SummaryStatus.GENERATED,
            generated_at=now,
        )
        return await self._summary_repo.upsert(generated_summary)

    async def _call_gemini(self, prompt: str) -> str:
        """Call the Gemini API or use test override."""
        if self._gemini_response_override is not None:
            return self._gemini_response_override

        # Real Gemini call (same pattern as GeminiTitleSimilarityAssessor)
        import google.generativeai as genai

        genai.configure(api_key=self._gemini_api_key)
        model = genai.GenerativeModel(self._gemini_model)
        response = await model.generate_content_async(prompt)
        return response.text  # type: ignore[no-any-return]

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse AI response JSON.

        Raises ValueError on malformed JSON or missing required fields.
        """
        # Try to extract JSON from possible markdown code blocks
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove markdown fences
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        parsed = json.loads(cleaned)

        if "summary_text" not in parsed:
            raise ValueError("AI response missing 'summary_text' field")

        return {
            "summary_text": parsed["summary_text"],
            "follow_up_suggestions": parsed.get("follow_up_suggestions", []),
        }
