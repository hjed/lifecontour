"""Prompt builder for daily journal summaries.

Constructs a structured prompt for the AI model, grounded in the day's
actual journal content and metadata.

**Forward-looking material is rendered for the current day only.** A summary of
last Tuesday describes last Tuesday, not what was scheduled after it, so the
agenda section is emitted only when the day being summarised is today in the
user's timezone — the same judgement the assembler makes before reading it. Two
guards for one rule is deliberate: the assembler's saves a query, this one is
what the rule can be asserted at without a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.settings.timezone_utils import (
    DEFAULT_TIMEZONE,
    format_datetime,
    now_in_tz,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from app.core.journal.models.agenda import AgendaEntry
    from app.core.journal.services.daily_summary_models import DailySummaryInput

# Truncate content beyond this length to keep prompts bounded
MAX_CONTENT_LENGTH = 500

# Caps on the agenda material one prompt may carry. Adding the agenda, and later
# the week's tasks and contact dates, grows a prompt that used to hold journals
# alone, so each input group is bounded rather than left to a busy day. Neither
# cap truncates silently: what is left out is counted in the prompt, because a
# model told "and 6 more" can say the day was full, while one handed a quietly
# shortened list will describe it as complete.
MAX_AGENDA_ENTRIES = 20
MAX_AGENDA_PARTICIPANTS = 10


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
        3. Today's agenda (current day only)
        4. Journal entries (title, content, types, contacts, mood)
        5. Previous summary (for incremental update)
        6. Output format specification
        """
        sections: list[str] = []

        # 1. System instructions — current time in the user's timezone
        now_local = now_in_tz(timezone, now)

        sections.append(self._build_system_instructions(now_local, timezone))

        # 2. Day overview (temporal context is relative to the user's local date)
        temporal_context = self._temporal_context(
            summary_input.summary_date, now_local.date()
        )
        sections.append(self._build_day_overview(summary_input, temporal_context))

        # 3. Today's agenda — nothing at all for any other day
        agenda_section = self._build_agenda(summary_input, temporal_context, timezone)
        if agenda_section:
            sections.append(agenda_section)

        # 4. Journal entries
        entries_section = self._build_journal_entries(summary_input)
        if entries_section:
            sections.append(entries_section)

        # 5. Previous summary
        if summary_input.previous_summary:
            sections.append(
                self._build_previous_summary(summary_input.previous_summary)
            )

        # 6. Output format
        sections.append(self._build_output_format())

        return "\n\n".join(sections)

    def _build_system_instructions(self, now: datetime, timezone: str) -> str:
        current_time = format_datetime(now, timezone)
        return (
            "You are summarising a user's day based on their journal entries.\n"
            f"Current System Time: {current_time}\n"
            "Times and dates are shown in the user's local timezone unless a "
            "different timezone is named beside them.\n"
            "Use this time context to differentiate between past events, today's events, and upcoming future events.\n"
            "Before writing the summary, use the available tools to gather context:\n"
            "- Use get_contact_journals to review recent meetings and interactions with each contact involved in the day's entries.\n"
            "- Use search_journals, get_contact, or global_search for any other context you need.\n"
            "Look for open follow-ups, commitments, or upcoming events the user should remember or action today.\n"
            "Keep the summary short.\n"
            "Be practical and descriptive rather than speculative.\n"
            "Do not invent information not present in the journals, the agenda or "
            "the tool results you were given.\n"
            "Do not invent commitments the user did not make.\n"
            "Do not rewrite the journal record — just summarise.\n"
            "Do not restate the day's agenda, journals or other listed material item "
            "by item — the user can already see those lists.\n"
            "Your value is in connecting them: what one implies for another, what "
            "needs preparing, what is likely to clash.\n"
            "If mood data is present, mention the general mood direction."
        )

    @staticmethod
    def _temporal_context(summary_date: date, today: date) -> str:
        """Where ``summary_date`` sits relative to the user's local today.

        Extracted from the overview because it is now two questions' answer: how
        to label the day, *and* whether forward-looking material belongs in the
        prompt at all.
        """
        if summary_date < today:
            return "Past"
        if summary_date == today:
            return "Today"
        return "Future"

    def _build_day_overview(
        self, summary_input: DailySummaryInput, temporal_context: str
    ) -> str:
        date_str = summary_input.summary_date.isoformat()

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

    def _build_agenda(
        self,
        summary_input: DailySummaryInput,
        temporal_context: str,
        timezone: str,
    ) -> str:
        """The day's scheduled events, for the current day and no other.

        An empty agenda contributes nothing rather than an empty heading: a
        heading with no rows under it reads to a model as a section it should
        account for, and a quiet day is not a fact worth a heading of its own.
        """
        if temporal_context != "Today" or not summary_input.agenda:
            return ""

        shown = summary_input.agenda[:MAX_AGENDA_ENTRIES]
        omitted = len(summary_input.agenda) - len(shown)

        lines = [
            "## Today's Agenda",
            "The events scheduled on this day, in the order the user sees them.",
            "Each time is the clock time on the event itself. Where that is not "
            "the user's own timezone the zone is named after it, and those times "
            "cannot be compared with the rest without converting them.",
            "Entries marked [CANCELLED] did not go ahead — never describe one as "
            "something the user is doing.",
        ]
        lines.extend(self._agenda_line(entry, timezone) for entry in shown)
        if omitted:
            lines.append(
                f"({omitted} further events on this day are not listed; the agenda "
                f"above is capped at {MAX_AGENDA_ENTRIES}.)"
            )
        return "\n".join(lines)

    @staticmethod
    def _agenda_line(entry: AgendaEntry, timezone: str) -> str:
        """One agenda entry as a single line.

        **The time comes from the clock columns, never from the instant.** An
        entry's ``starts_at`` is stored in whatever zone wrote it, so rendering a
        clock time from it would assert an hour in a zone the row does not
        record — the defect the agenda's own read exists to avoid. A timed event
        with no clock columns therefore gets no time rather than a wrong one.

        **And those clock times are the *event's*, not the reader's.** Migration
        0045 derives them ``AT TIME ZONE jci.timezone``, so a 09:00 New York
        meeting stores ``09:00`` however far from New York the user is; a null
        zone means UTC. A zone that is not the user's is therefore named beside
        the time, because otherwise that meeting reads to the model as a morning
        appointment on a Sydney day — the failure the API design document
        predicts for any surface that renders these values bare.
        """
        parts: list[str] = []
        if entry.is_cancelled:
            parts.append("[CANCELLED]")

        # Only a rendered time can be misread as the user's, so the zone is
        # named with the time or not at all: an all-day entry happens on a date
        # and has no clock value for a zone to qualify.
        zone = entry.timezone or DEFAULT_TIMEZONE
        elsewhere = f" ({zone})" if zone != timezone else ""

        if entry.is_all_day:
            parts.append("All day:")
        elif entry.start_time is not None and entry.end_time is not None:
            parts.append(f"{entry.start_time:%H:%M}-{entry.end_time:%H:%M}{elsewhere}:")
        elif entry.start_time is not None:
            parts.append(f"{entry.start_time:%H:%M}{elsewhere}:")

        parts.append(entry.title)
        if entry.location:
            parts.append(f"(at {entry.location})")

        names = [person.name for person in entry.participants]
        if names:
            shown = names[:MAX_AGENDA_PARTICIPANTS]
            omitted = len(names) - len(shown)
            with_clause = f"with {', '.join(shown)}"
            if omitted:
                with_clause += f" and {omitted} more"
            parts.append(with_clause)

        return f"- {' '.join(parts)}"

    def _build_journal_entries(self, summary_input: DailySummaryInput) -> str:
        if not summary_input.journals:
            return ""

        lines = ["## Journal Entries"]
        for i, entry in enumerate(summary_input.journals, 1):
            lines.append(f"\n### Entry {i}: {entry.title}")
            if entry.types:
                lines.append(f"Types: {', '.join(entry.types)}")
            if entry.series_names:
                lines.append(
                    f"Series: {', '.join(entry.series_names)} "
                    "(recurring/related series this entry belongs to)"
                )
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
            '{"summary_text": "Your summary of the day here."}\n'
            "The summary_text must be exactly two paragraphs separated by a blank line:\n"
            "1. A concise summary of the day (mention the general mood direction if mood data is present).\n"
            "2. Things the user should remember or action today, drawing on recent meetings and interactions "
            "with the day's contacts. If there is genuinely nothing to remember or action, say so briefly."
        )
