"""Prompt builder for daily journal summaries.

Constructs a structured prompt for the AI model, grounded in the day's
actual journal content and metadata.
"""

from __future__ import annotations

from datetime import datetime

from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.settings.timezone_utils import (
    DEFAULT_TIMEZONE,
    format_datetime,
    now_in_tz,
)

# Truncate content beyond this length to keep prompts bounded
MAX_CONTENT_LENGTH = 500


class DailySummaryPromptBuilder:
    """Builds structured prompts for daily summary generation."""

    def build(
        self,
        summary_input: DailySummaryInput,
        now: datetime | None = None,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> str:
        """Build a complete prompt from the assembled day input.

        All times/dates are rendered in ``timezone`` (the user's preferred
        timezone) with explicit timezone labels so the model never assumes UTC.

        Sections:
        1. System instructions
        2. Day overview (date, counts)
        3. Journal entries (title, content, types, contacts, mood)
        4. Previous summary (for incremental update)
        5. Output format specification
        """
        sections: list[str] = []

        # 1. System instructions — current time in the user's timezone
        now_local = now_in_tz(timezone, now)

        sections.append(self._build_system_instructions(now_local, timezone))

        # 2. Day overview (temporal context is relative to the user's local date)
        sections.append(self._build_day_overview(summary_input, now_local))

        # 3. Journal entries
        entries_section = self._build_journal_entries(summary_input)
        if entries_section:
            sections.append(entries_section)

        # 4. Previous summary
        if summary_input.previous_summary:
            sections.append(
                self._build_previous_summary(summary_input.previous_summary)
            )

        # 5. Output format
        sections.append(self._build_output_format())

        return "\n\n".join(sections)

    def _build_system_instructions(self, now: datetime, timezone: str) -> str:
        current_time = format_datetime(now, timezone)
        return (
            "You are summarising a user's day based on their journal entries.\n"
            f"Current System Time: {current_time}\n"
            "All times and dates are shown in the user's local timezone.\n"
            "Use this time context to differentiate between past events, today's events, and upcoming future events.\n"
            "Be short, practical, and descriptive rather than speculative.\n"
            "Do not invent information not present in the journals.\n"
            "Do not rewrite the journal record — just summarise.\n"
            "If mood data is present, mention the general mood direction."
        )

    def _build_day_overview(
        self, summary_input: DailySummaryInput, now: datetime
    ) -> str:
        date_str = summary_input.summary_date.isoformat()

        now_date = now.date()
        if summary_input.summary_date < now_date:
            temporal_context = "Past"
        elif summary_input.summary_date == now_date:
            temporal_context = "Today"
        else:
            temporal_context = "Future"

        lines = [
            f"## Day Overview: {date_str} ({temporal_context})",
            f"- Journal count: {summary_input.journal_count}",
            f"- Event count: {summary_input.event_count}",
        ]
        if summary_input.contact_names:
            contacts_str = ", ".join(sorted(set(summary_input.contact_names)))
            lines.append(f"- Contacts involved: {contacts_str}")
        if summary_input.mood_values:
            avg = sum(summary_input.mood_values) / len(summary_input.mood_values)
            lines.append(f"- Average mood: {avg:.1f}")
        return "\n".join(lines)

    def _build_journal_entries(self, summary_input: DailySummaryInput) -> str:
        if not summary_input.journals:
            return ""

        lines = ["## Journal Entries"]
        for i, entry in enumerate(summary_input.journals, 1):
            lines.append(f"\n### Entry {i}: {entry.title}")
            if entry.types:
                lines.append(f"Types: {', '.join(entry.types)}")
            if entry.contact_names:
                lines.append(f"Contacts: {', '.join(entry.contact_names)}")
            if entry.mood_value is not None:
                lines.append(f"Mood: {entry.mood_value}")
            if entry.energy_level is not None:
                lines.append(f"Energy: {entry.energy_level}")
            content = entry.content
            if len(content) > MAX_CONTENT_LENGTH:
                content = content[:MAX_CONTENT_LENGTH] + "..."
            lines.append(f"Content: {content}")

        return "\n".join(lines)

    def _build_previous_summary(self, previous_summary: str) -> str:
        return (
            "## Previous Summary (for context — update or replace as needed)\n"
            f"{previous_summary}"
        )

    def _build_output_format(self) -> str:
        return (
            "## Output Format\n"
            "Respond with a JSON object containing a single field:\n"
            '{"summary_text": "Your concise summary of the day here."}\n'
            "The summary_text should be 1-3 sentences."
        )
