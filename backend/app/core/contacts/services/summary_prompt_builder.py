"""Prompt builder for AI contact summary generation.

Constructs structured prompts from assembled input data, including
incremental context (prior summary), long-term activity statistics,
and tone/safety guardrails per the product specification.
"""

from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.contacts.services.summary_models import (
    SummaryInput,
)


class SummaryPromptBuilder:
    """Builds prompts for AI summary generation."""

    MAX_PROMPT_CHARS = 30_000
    _MAX_NOTE_CHARS = 500
    _MAX_JOURNAL_CONTENT_CHARS = 1000

    def build(self, summary_input: SummaryInput) -> str:
        """Build a structured prompt from assembled input data."""
        sections: list[str] = []

        tz: tzinfo
        try:
            tz = ZoneInfo(summary_input.timezone)
        except ZoneInfoNotFoundError:
            tz = UTC

        now = datetime.now(tz=tz)

        # System instructions
        sections.append(
            self._system_instructions(now, tz.key if hasattr(tz, "key") else str(tz))
        )

        # Contact identity
        sections.append(self._contact_section(summary_input))

        # Previous summary (incremental context)
        if summary_input.previous_summary:
            sections.append(
                self._previous_summary_section(summary_input.previous_summary)
            )

        # Long-term activity statistics
        if summary_input.activity_stats:
            sections.append(self._activity_stats_section(summary_input))

        # Recent notes
        if summary_input.recent_notes:
            sections.append(self._notes_section(summary_input.recent_notes))

        # Recent journals
        if summary_input.recent_journals:
            sections.append(
                self._format_journals_section(
                    "Recent Linked Journals mentioning the Contact or where the Contact was a Particpant",
                    summary_input.recent_journals,
                )
            )

        # Future journals
        if summary_input.future_journals:
            sections.append(
                self._format_journals_section(
                    "Upcoming Scheduled Events with the Contact",
                    summary_input.future_journals,
                )
            )

        # Relationships
        if summary_input.relationships:
            sections.append(self._relationships_section(summary_input.relationships))

        # Recent history
        if summary_input.recent_history:
            sections.append(self._history_section(summary_input.recent_history))

        # Important dates
        if summary_input.important_dates:
            sections.append(self._dates_section(summary_input.important_dates))

        # Output format
        sections.append(self._output_format())

        prompt = "\n\n".join(sections)

        # Truncate if too long
        if len(prompt) > self.MAX_PROMPT_CHARS:
            prompt = (
                prompt[: self.MAX_PROMPT_CHARS - 100]
                + "\n\n[Content truncated for length]"
            )

        return prompt

    def _system_instructions(self, now: datetime, timezone_str: str) -> str:
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")
        return (
            "You are an AI assistant that generates concise, evidence-grounded "
            "interaction summaries for a personal contact management system.\n\n"
            f"Current System Time: {current_time} {timezone_str}\n"
            "Use this time context to differentiate between past and future events.\n\n"
            "Guidelines:\n"
            "- Be conservative and grounded in the evidence provided\n"
            "- Avoid overstating certainty or making intrusive assumptions\n"
            "- Focus on unresolved follow-ups, recent interactions, "
            "  and suggested conversation prompts\n"
            "- Stay factual and helpful for reconnecting with the contact\n"
            "- If updating from a previous summary, preserve important "
            "long-term context while incorporating new information"
        )

    def _contact_section(self, inp: SummaryInput) -> str:
        lines = [f"## Contact: {inp.contact_name}"]
        if inp.company:
            lines.append(f"Company: {inp.company}")
        if inp.job_title:
            lines.append(f"Role: {inp.job_title}")
        return "\n".join(lines)

    def _previous_summary_section(self, prev: str) -> str:
        truncated = prev[: self._MAX_JOURNAL_CONTENT_CHARS]
        return (
            "## Previous Summary\n"
            "The following is the previous AI-generated summary. "
            "Update and refine it based on the new information below, "
            "preserving important historical context:\n\n"
            f"{truncated}"
        )

    def _activity_stats_section(self, inp: SummaryInput) -> str:
        lines = ["## Long-Term Activity Overview"]
        for bucket in inp.activity_stats:
            lines.append(
                f"- {bucket.period_label}: {bucket.event_count} events or journals related to the contact"
            )
        return "\n".join(lines)

    def _notes_section(self, notes: list[str]) -> str:
        lines = ["## Recent Notes"]
        for note in notes:
            truncated = note[: self._MAX_NOTE_CHARS]
            lines.append(f"- {truncated}")
        return "\n".join(lines)

    def _format_journals_section(
        self, heading: str, journals: list[dict[str, Any]]
    ) -> str:
        lines = [f"## {heading}"]
        for j in journals:
            title = str(j.get("title", ""))[:200]
            content = str(j.get("content", ""))[: self._MAX_JOURNAL_CONTENT_CHARS]
            date = j.get("date", "")

            meta_parts = []
            if date:
                meta_parts.append(date)

            types = j.get("journal_types", [])
            if types:
                meta_parts.append(f"types: {', '.join(types)}")

            rel = j.get("relationship_type")
            if rel:
                rel_str = f"role of contact: {rel}"
                status = j.get("status")
                if status:
                    rel_str += f" ({status})"
                meta_parts.append(rel_str)

            meta_str = f" ({'; '.join(meta_parts)})" if meta_parts else ""

            entry = f"- **{title}**{meta_str}: {content}"
            lines.append(entry)
        return "\n".join(lines)

    def _relationships_section(self, rels: list[str]) -> str:
        lines = ["## Relationships"]
        for r in rels:
            lines.append(f"- {r}")
        return "\n".join(lines)

    def _history_section(self, history: list[str]) -> str:
        lines = ["## Recent Changes"]
        for h in history:
            lines.append(f"- {h}")
        return "\n".join(lines)

    def _dates_section(self, dates: list[str]) -> str:
        lines = ["## Important Dates"]
        for d in dates:
            lines.append(f"- {d}")
        return "\n".join(lines)

    def _output_format(self) -> str:
        return (
            "## Output Format\n"
            "Respond with a JSON object containing:\n"
            "```json\n"
            "{\n"
            '  "summary_text": "A concise 2-4 sentence summary of the user\'s relationship with the contact...",\n'
            '  "follow_up_suggestions": [\n'
            '    "Specific actionable follow-up suggestion 1",\n'
            '    "Specific actionable follow-up suggestion 2"\n'
            "  ]\n"
            "}\n"
            "```\n"
            "The summary_text should help the user reconnect effectively and remember actions and important details. "
            "Include 1-3 follow_up_suggestions that are specific and actionable."
        )
