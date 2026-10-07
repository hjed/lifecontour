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
    SummaryDisabledReason,
    SummaryStatus,
)
from core_shared.models.contacts.value_objects import Provenance

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
    JournalSeriesRepository,
)
from app.core.settings.timezone_utils import DEFAULT_TIMEZONE, isoformat_in_tz

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.contacts.models.repositories import ContactEventPublisher
    from app.core.contacts.services.summary_prompt_builder import (
        SummaryPromptBuilder,
    )

logger = logging.getLogger(__name__)


def _relationship_label(rel_type: Any) -> str:
    """Return a human-readable label for a relationship type enum or value."""
    return str(rel_type.value) if hasattr(rel_type, "value") else str(rel_type)


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
    MAX_FUTURE_JOURNALS = 6
    MAX_NOTES = 10
    MAX_HISTORY_ENTRIES = 20

    def __init__(
        self,
        contact_repo: ContactRepository,
        history_repo: ContactFieldHistoryRepository,
        journal_relationship_repo: JournalContactRelationshipRepository,
        journal_repo: JournalRepository,
        summary_repo: ContactSummaryRepository,
        series_repo: JournalSeriesRepository | None = None,
    ) -> None:
        self._contact_repo = contact_repo
        self._history_repo = history_repo
        self._journal_relationship_repo = journal_relationship_repo
        self._journal_repo = journal_repo
        self._summary_repo = summary_repo
        self._series_repo = series_repo

    async def assemble(
        self, contact_id: int, timezone: str = DEFAULT_TIMEZONE
    ) -> SummaryInput | None:
        """Assemble bounded input data for summary generation.

        Journal event dates are rendered in the user's ``timezone`` with an
        explicit offset so the model never has to assume UTC.

        Returns None if the contact does not exist.

        Generation runs from a background consumer with no acting user, so the
        contact is read as its own owner: the summary describes the contact to
        that user.
        """
        owner = await self._contact_repo.find_owner_id(contact_id)
        if owner is None:
            return None
        contact = await self._contact_repo.find_by_id(contact_id, user_id=owner)
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

        # Relationships. Each is rendered with an explicit subject, target, and a
        # disclaimer so the model never confuses a relationship between two
        # contacts with a relationship to the user. Phrasing stays strictly
        # third-person ("the user", the CRM owner) rather than "you"/"your",
        # since in this prompt "you" is the AI assistant, not the user.
        # Relationships are loaded for both directions, so pick the *other*
        # party (and invert the type) when this contact is the target side.
        rels = getattr(contact, "relationships", None) or []
        relationships = []
        for r in rels:
            if getattr(r, "to_user", False):
                label = _relationship_label(r.relationship_type)
                relationships.append(
                    f"{contact_name} is the {label} of the user "
                    "(a relationship to the user, the CRM owner)"
                )
                continue

            if r.from_contact_id == contact_id:
                other = getattr(r, "to_contact_name", None) or "another contact"
                label = _relationship_label(r.relationship_type)
            else:
                other = getattr(r, "from_contact_name", None) or "another contact"
                label = _relationship_label(r.get_inverse_type())

            relationships.append(
                f"{contact_name} is the {label} of {other} "
                "(another contact, not the user)"
            )

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
            important_dates.append(": ".join(parts))

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

        # Fetch recent and future journals (bounded)
        recent_journals: list[dict[str, Any]] = []
        future_journals: list[dict[str, Any]] = []
        journal_dicts_by_id: list[tuple[int, str | None, dict[str, Any]]] = []

        # We check all relationships to find future ones, but prioritize recent ones for past events
        for jr in all_j_rels:
            if (
                len(recent_journals) >= self.MAX_JOURNALS
                and len(future_journals) >= self.MAX_FUTURE_JOURNALS
            ):
                break

            journal = await self._journal_repo.find_by_id(jr.journal_id)
            if not journal:
                continue

            journal_date_str = ""
            is_future = False

            if hasattr(journal, "event_date_range") and journal.event_date_range:
                start = getattr(journal.event_date_range, "start", None)
                if start:
                    if isinstance(start, datetime):
                        journal_date_str = isoformat_in_tz(start, timezone)
                        is_future = start > now
                    elif hasattr(start, "isoformat"):
                        journal_date_str = start.isoformat()
                        is_future = start > now.date()
                    else:
                        journal_date_str = str(start)

            if hasattr(self._journal_repo, "get_types"):
                journal_types = await self._journal_repo.get_types(jr.journal_id)
            else:
                journal_types = ["NOTE"]

            # Extract relationship type and status
            rel_type = (
                jr.relationship_type.value
                if hasattr(jr.relationship_type, "value")
                else str(jr.relationship_type)
            )

            status = None
            if hasattr(jr, "status") and jr.status is not None:
                status = (
                    jr.status.value if hasattr(jr.status, "value") else str(jr.status)
                )

            journal_dict = {
                "title": getattr(journal, "title", ""),
                "content": getattr(journal, "content", ""),
                "date": journal_date_str,
                "relationship_type": rel_type,
                "status": status,
                "journal_types": journal_types,
                "series": [],
            }

            retained = False
            if is_future:
                if len(future_journals) < self.MAX_FUTURE_JOURNALS:
                    future_journals.append(journal_dict)
                    retained = True
            else:
                # Only include past events if they are in the recent window,
                # or if we want to fill up the recent_journals?
                # The previous logic only took from recent_j_rels.
                # Let's check if jr is in recent_j_rels
                created = getattr(jr, "created_at", None)
                if created and created >= window_start:
                    if len(recent_journals) < self.MAX_JOURNALS:
                        recent_journals.append(journal_dict)
                        retained = True

            # Series are only looked up for journals that made it into the
            # prompt input; dropped dicts would waste the bulk lookup.
            if retained:
                journal_dicts_by_id.append(
                    (jr.journal_id, getattr(journal, "user_id", None), journal_dict)
                )

        # Attach series membership (one bulk lookup across included journals)
        if self._series_repo is not None and journal_dicts_by_id:
            journal_user_id = next(
                (uid for _, uid, _ in journal_dicts_by_id if uid), None
            )
            if journal_user_id is not None:
                series_names_by_journal = (
                    await self._series_repo.get_series_names_for_journal_ids(
                        [jid for jid, _, _ in journal_dicts_by_id],
                        journal_user_id,
                    )
                )
                for jid, _, journal_dict in journal_dicts_by_id:
                    journal_dict["series"] = series_names_by_journal.get(jid, [])

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
            future_journals=future_journals,
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

        # Determine the earliest interaction (filter out None created_at)
        created_dates = [getattr(jr, "created_at", None) for jr in older_journal_rels]
        valid_dates = [d for d in created_dates if d is not None]
        earliest = min(valid_dates, default=window_end)

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
        event_publisher: ContactEventPublisher | None = None,
        connection: AsyncConnection | None = None,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self._input_assembler = input_assembler
        self._activity_checker = activity_checker
        self._prompt_builder = prompt_builder
        self._summary_repo = summary_repo
        self._gemini_api_key = gemini_api_key
        self._gemini_model = gemini_model
        self._gemini_response_override = _gemini_response_override
        # ITER12-003 Phase 2: summary history is produced by the projection from
        # the ContactSummaryUpdated event published here (the synchronous
        # history write was removed). The event is written to the outbox on
        # ``connection`` so it commits atomically with the summary row.
        self._event_publisher = event_publisher
        self._connection = connection
        self._timezone = timezone

    def _assert_single_connection(self) -> None:
        """Verify the event publisher shares ``self._connection`` so the
        ContactSummaryUpdated event is written to the outbox on the same
        connection the summary row was upserted on (and commits atomically).

        Only meaningful when a real connection + publisher are wired (the
        consumer path); unit tests pass a ``None`` connection and skip the check.
        """
        if self._event_publisher is None or self._connection is None:
            return
        publisher_conn = getattr(self._event_publisher, "conn", None)
        if publisher_conn is not self._connection:
            raise RuntimeError(
                "SummaryGenerator event_publisher and connection must share one "
                "connection so the summary row and ContactSummaryUpdated commit "
                "atomically"
            )

    async def _record_summary_history(
        self, contact_id: int, changed_fields: dict[str, Any]
    ) -> None:
        """Publish ContactSummaryUpdated so the history projection records the change.

        ITER12-003 Phase 2 removed the synchronous ``record_summary_change`` write;
        history is now derived from this event. The event is written to the outbox
        on ``self._connection`` — the same connection the summary row was upserted
        on — so the two commit atomically. No publisher (unit tests) → no-op.
        """
        if self._event_publisher is None:
            return
        from app.core.contacts.models.events import ContactSummaryUpdated

        self._assert_single_connection()
        await self._event_publisher.publish(
            ContactSummaryUpdated(
                contact_id=contact_id,
                changed_fields=changed_fields,
                source=Provenance.SUMMARY_REGENERATION,
                changed_by="system",
                transaction=self._connection,
            )
        )

    async def generate(self, contact_id: int) -> ContactSummary | None:
        """Generate or regenerate an AI summary for a contact.

        A summary the user disabled is skipped. A summary auto-paused for low
        activity is re-evaluated: it stays paused while activity is still low
        and resumes (the pause is lifted) once there is enough to summarise.

        Returns the resulting ContactSummary, or None if generation was skipped.
        """
        if not self._gemini_api_key:
            logger.info("No Gemini API key configured, skipping summary generation")
            return None

        # Check existing summary state
        # Read without a lock: generation includes a slow AI call, and row locks
        # are kept out of that window (#970). Every write below is guarded
        # instead, so a user who disables generation meanwhile keeps their choice.
        existing = await self._summary_repo.find_by_contact_id(contact_id)

        # A user's disable is sticky: skip it whether or not it has an override
        if existing and existing.is_user_disabled:
            logger.info(
                "Contact %d summary is disabled, skipping generation",
                contact_id,
            )
            return existing
        was_paused = existing is not None and existing.is_disabled

        # Assemble input first to verify contact exists
        summary_input = await self._input_assembler.assemble(contact_id, self._timezone)
        if summary_input is None:
            logger.warning("Contact %d not found, cannot generate summary", contact_id)
            return None

        # Early exit if no journals will be included in the prompt
        if not summary_input.recent_journals and not summary_input.future_journals:
            logger.info(
                "Contact %d has no journals for prompt, skipping generation", contact_id
            )
            if was_paused:
                # Nothing can be generated without a journal, so lifting the pause
                # here would only erase the summary. Stay paused; the pause is
                # re-evaluated once a journal gives generation something to use.
                return existing
            if existing and (
                existing.summary_text
                or existing.follow_up_suggestions
                or existing.status != SummaryStatus.GENERATED
            ):
                cleared_summary = self._merge_with_existing(
                    existing,
                    contact_id=contact_id,
                    summary_text="",
                    follow_up_suggestions=[],
                    status=SummaryStatus.GENERATED,
                    generated_at=datetime.now(tz=UTC),
                )
                return await self._write_from_generation(contact_id, cleared_summary)
            return existing

        # Set status to GENERATING (only after confirming contact exists)
        generating = await self._summary_repo.update_status_unless_user_disabled(
            contact_id, SummaryStatus.GENERATING.value
        )
        if generating is None:
            # No row matched: the user disabled it since the read, or there is
            # no row yet. Only a disable stops the run, before any AI call.
            stored = await self._summary_repo.find_by_contact_id(contact_id)
            if stored is not None and stored.is_user_disabled:
                return self._keep_user_disable(stored)
        else:
            # Decide from the row as stored at this write, so anything the user
            # committed since the first read (such as an override) counts.
            existing = generating
            was_paused = generating.is_disabled

        # Check low activity
        if self._activity_checker.should_auto_disable(summary_input, existing):
            logger.info(
                "Contact %d has low activity, auto-disabling summary",
                contact_id,
            )
            disabled_summary = self._merge_with_existing(
                existing,
                contact_id=contact_id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
                disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
            )
            result_summary = await self._summary_repo.upsert_from_generation(
                disabled_summary
            )
            if result_summary is None:
                return await self._user_disabled_meanwhile(contact_id)
            if self._event_publisher and (not existing or not existing.is_disabled):
                disabled_changed_fields = {
                    "is_disabled": (
                        existing.is_disabled if existing else False,
                        True,
                    )
                }
                try:
                    await self._record_summary_history(
                        contact_id, disabled_changed_fields
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "Failed to record history/event for contact %s "
                        "auto-disable: %s",
                        contact_id,
                        e,
                    )
            return result_summary

        # Build prompt
        prompt = self._prompt_builder.build(summary_input, timezone=self._timezone)

        # Call AI
        try:
            raw_response = await self._call_gemini(prompt)
            result = self._parse_response(raw_response)
        except Exception as e:
            logger.exception("AI generation failed for contact %d: %s", contact_id, e)
            failed_summary = self._merge_with_existing(
                existing,
                contact_id=contact_id,
                status=SummaryStatus.FAILED,
                is_disabled=False,
                disabled_reason=None,
            )
            return await self._write_from_generation(contact_id, failed_summary)

        # Persist result
        now = datetime.now(tz=UTC)
        generated_summary = self._merge_with_existing(
            existing,
            contact_id=contact_id,
            summary_text=result["summary_text"],
            follow_up_suggestions=result.get("follow_up_suggestions", []),
            status=SummaryStatus.GENERATED,
            generated_at=now,
            is_disabled=False,
            disabled_reason=None,
        )
        result_summary = await self._summary_repo.upsert_from_generation(
            generated_summary
        )
        if result_summary is None:
            return await self._user_disabled_meanwhile(contact_id)

        if self._event_publisher and (
            not existing
            or existing.summary_text != result["summary_text"]
            or was_paused
        ):
            summary_changed_fields: dict[str, Any] = {
                "summary_text": (
                    existing.summary_text if existing else None,
                    result["summary_text"],
                )
            }
            if was_paused:
                # Mirror the auto-disable diff so history shows the pause lifting
                summary_changed_fields["is_disabled"] = (True, False)
            try:
                await self._record_summary_history(contact_id, summary_changed_fields)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Failed to record history/event for contact %s "
                    "summary generation: %s",
                    contact_id,
                    e,
                )

        return result_summary

    async def _write_from_generation(
        self, contact_id: int, summary: ContactSummary
    ) -> ContactSummary | None:
        """Persist ``summary`` unless the user disabled generation since the read."""
        written = await self._summary_repo.upsert_from_generation(summary)
        if written is None:
            return await self._user_disabled_meanwhile(contact_id)
        return written

    async def _user_disabled_meanwhile(self, contact_id: int) -> ContactSummary | None:
        """Return the stored summary after a guarded write was skipped."""
        stored = await self._summary_repo.find_by_contact_id(contact_id)
        return self._keep_user_disable(stored) if stored is not None else None

    @staticmethod
    def _keep_user_disable(stored: ContactSummary) -> ContactSummary:
        """Log that a user's mid-run disable was kept and return their row."""
        logger.info(
            "Contact %d summary was disabled during generation; keeping that choice",
            stored.contact_id,
        )
        return stored

    async def _call_gemini(self, prompt: str) -> str:
        """Call the Gemini API or use test override."""
        if self._gemini_response_override is not None:
            return self._gemini_response_override

        import asyncio

        from fastmcp import Client
        from google import genai

        from app.mcp.shared.read_only_tools import (
            build_gemini_session_config,
            create_read_only_mcp_server,
        )

        read_only_mcp = await create_read_only_mcp_server("Summary Generation Tools")

        client = genai.Client(api_key=self._gemini_api_key)

        max_attempts = 3
        base_delay = 1.0

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

    @staticmethod
    def _merge_with_existing(
        existing: ContactSummary | None,
        **overrides: Any,
    ) -> ContactSummary:
        """Create a ContactSummary preserving existing fields not being overridden.

        Ensures user overrides, disabled flags, and other persisted state are
        carried forward rather than silently cleared by upsert.
        """
        if existing is None:
            return ContactSummary(**overrides)

        return ContactSummary(
            contact_id=overrides.get("contact_id", existing.contact_id),
            summary_text=overrides.get("summary_text", existing.summary_text),
            follow_up_suggestions=overrides.get(
                "follow_up_suggestions", existing.follow_up_suggestions
            ),
            status=overrides.get("status", existing.status),
            generated_at=overrides.get("generated_at", existing.generated_at),
            is_disabled=overrides.get("is_disabled", existing.is_disabled),
            disabled_reason=overrides.get("disabled_reason", existing.disabled_reason),
            is_user_override=overrides.get(
                "is_user_override", existing.is_user_override
            ),
            user_override_text=overrides.get(
                "user_override_text",
                getattr(existing, "user_override_text", None),
            ),
        )

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

        summary_text = parsed["summary_text"]
        if not isinstance(summary_text, str) or not summary_text.strip():
            raise ValueError("AI response 'summary_text' must be a non-empty string")

        # Validate follow_up_suggestions is a list of strings
        suggestions_raw = parsed.get("follow_up_suggestions", [])
        if not isinstance(suggestions_raw, list):
            suggestions_raw = []
        suggestions = [str(s) for s in suggestions_raw if s is not None]

        return {
            "summary_text": parsed["summary_text"],
            "follow_up_suggestions": suggestions,
        }
