"""Prompt builder for daily journal summaries.

Constructs a structured prompt for the AI model, grounded in the day's
actual journal content and metadata.

**Forward-looking material is rendered for the current day only.** A summary of
last Tuesday describes last Tuesday, not what was scheduled after it, so the
agenda and task sections are emitted only when the day being summarised is
today in the user's timezone — the same judgement the assembler makes before
reading either. Two guards for one rule is deliberate: the assembler's saves a
query, this one is what the rule can be asserted at without a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.settings.timezone_utils import (
    DEFAULT_TIMEZONE,
    format_datetime,
    now_in_tz,
    resolve_timezone,
    to_user_tz,
)

if TYPE_CHECKING:
    from datetime import date, datetime, time

    from core_shared.models.tasks import TaskReadModel

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

# The week's tasks get the same treatment and the same numbers, deliberately:
# two groups of one-line commitments budgeted differently would need a reason,
# and there is none. What bounds the group underneath is the seven-day window
# itself; these bound the pathological week within it.
MAX_TASK_ENTRIES = 20
MAX_TASK_CONTACTS = 10


def _with_people(names: list[str], cap: int) -> str | None:
    """``with A, B and 2 more`` — or nothing at all when there is nobody.

    Shared by the agenda's participants and a task's contacts because it is one
    concept, not two that happen to look alike: name the people, cap the list,
    and **count** what was left out rather than trimming it silently. A model
    told "and 2 more" can say a meeting was crowded; one handed a quietly
    shortened list will describe it as complete.

    Returning ``None`` rather than an empty string keeps the caller's decision
    ("is there a clause to append?") at the caller, where the rest of the line
    is being assembled.
    """
    if not names:
        return None

    shown = names[:cap]
    omitted = len(names) - len(shown)
    clause = f"with {', '.join(shown)}"
    if omitted:
        clause += f" and {omitted} more"
    return clause


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
        4. Tasks due in the week ahead (current day only)
        5. Journal entries (title, content, types, contacts, mood)
        6. Previous summary (for incremental update)
        7. Output format specification
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

        # 4. The week's commitments — nothing at all for any other day
        tasks_section = self._build_upcoming_tasks(summary_input, temporal_context)
        if tasks_section:
            sections.append(tasks_section)

        # 5. Journal entries
        entries_section = self._build_journal_entries(summary_input)
        if entries_section:
            sections.append(entries_section)

        # 6. Previous summary
        if summary_input.previous_summary:
            sections.append(
                self._build_previous_summary(summary_input.previous_summary)
            )

        # 7. Output format
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
            # Widened rather than joined by a second sentence: two grounding
            # rules naming different sources is a contradiction the model is
            # free to resolve by discarding whichever group is newest.
            "Do not invent information not present in the journals, the agenda, "
            "the tasks or the tool results you were given.\n"
            "Do not invent commitments the user did not make.\n"
            "Do not rewrite the journal record — just summarise.\n"
            "Do not restate the day's agenda, journals, tasks or other listed "
            "material item by item — the user can already see those lists.\n"
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
            "Every time below is the user's own local time, so they can be "
            "compared with each other directly. Where an event belongs to a "
            "different timezone, its own local time and zone follow in brackets.",
            "Entries marked [CANCELLED] did not go ahead — never describe one as "
            "something the user is doing.",
        ]
        lines.extend(
            self._agenda_line(entry, timezone, summary_input.summary_date)
            for entry in shown
        )
        if omitted:
            lines.append(
                f"({omitted} further events on this day are not listed; the agenda "
                f"above is capped at {MAX_AGENDA_ENTRIES}.)"
            )
        return "\n".join(lines)

    @classmethod
    def _agenda_line(cls, entry: AgendaEntry, timezone: str, day: date) -> str:
        """One agenda entry as a single line.

        **The time comes from the clock columns, never from the instant.** An
        entry's ``starts_at`` is stored in whatever zone wrote it, so rendering a
        clock time from it would assert an hour in a zone the row does not
        record — the defect the agenda's own read exists to avoid. A timed event
        with no clock columns therefore gets no time rather than a wrong one.

        **And those clock times are the *event's*, not the reader's.** Migration
        0045 derives them ``AT TIME ZONE jci.timezone``, so a 09:00 New York
        meeting stores ``09:00`` however far from New York the user is; a null
        zone means UTC.

        Naming the zone beside such a time is **not enough on its own**, because
        the entry is on this agenda by *instant* overlap and its own local date
        may be the day before or after: 23:00 on a New York Monday is on a
        Sydney user's Tuesday, and "23:00 (America/New_York)" under a Tuesday
        heading reads as a late-night Tuesday event when it is really 15:00
        Tuesday afternoon. So an entry in another zone leads with the **user's**
        clock time — derived from the stored instant, which is arithmetic rather
        than invention — and carries the event's own time and zone behind it.
        Every time on the agenda is then directly comparable with every other,
        which is what the model needs to notice a clash.
        """
        parts: list[str] = []
        if entry.is_cancelled:
            parts.append("[CANCELLED]")

        # Only a rendered time can be misread, so the zone travels with the time
        # or not at all: an all-day entry happens on a date and has no clock
        # value for a zone to qualify.
        zone = entry.timezone or DEFAULT_TIMEZONE
        elsewhere = zone != timezone

        if entry.is_all_day:
            parts.append("All day:")
        elif entry.start_time is not None:
            reader = resolve_timezone(timezone)
            local = cls._reader_span(
                to_user_tz(entry.starts_at, reader),
                to_user_tz(entry.ends_at, reader),
                day,
            )
            if elsewhere:
                parts.append(f"{local} ({cls._event_local_time(entry)} {zone}):")
            else:
                parts.append(f"{local}:")

        parts.append(entry.title)
        if entry.location:
            parts.append(f"(at {entry.location})")

        people = _with_people(
            [person.name for person in entry.participants], MAX_AGENDA_PARTICIPANTS
        )
        if people:
            parts.append(people)

        return f"- {' '.join(parts)}"

    @staticmethod
    def _span(start: datetime | time, end: datetime | time | None) -> str:
        """``HH:MM-HH:MM``, or just the start when there is no end."""
        return f"{start:%H:%M}-{end:%H:%M}" if end is not None else f"{start:%H:%M}"

    @staticmethod
    def _reader_span(start: datetime, end: datetime, day: date) -> str:
        """The entry's span in the reader's zone, dated when it leaves ``day``.

        **A timed entry can begin before this day and end after it.** The agenda
        matches timed events by overlap precisely so that a multi-day trip
        appears on the days in the middle of it, and for those the two clock
        values belong to different dates: a Monday-to-Wednesday event shows
        ``09:00`` and ``17:00`` that are two days apart. Rendered as
        ``09:00-17:00`` on the Tuesday it reads as an ordinary Tuesday
        appointment, and as ``09:00-09:00`` — the common case, where a trip
        starts and ends at the same hour — it reads as an event of no duration
        at all. Both invite the model to reason about a clash that does not
        exist and to miss the one that does.

        So the dates are shown whenever either end falls outside ``day``, and
        omitted when neither does, which is the ordinary case and the one that
        should stay terse.
        """
        if start.date() == day and end.date() == day:
            return f"{start:%H:%M}-{end:%H:%M}"
        return f"{start:%d %b %H:%M} - {end:%d %b %H:%M}"

    @classmethod
    def _event_local_time(cls, entry: AgendaEntry) -> str:
        """The entry's clock columns — its own local time, whatever zone that is."""
        return cls._span(entry.start_time, entry.end_time) if entry.start_time else ""

    @classmethod
    def _build_upcoming_tasks(
        cls, summary_input: DailySummaryInput, temporal_context: str
    ) -> str:
        """The commitments due in the week ahead, for the current day and no other.

        The second of the two guards on the same rule, the first being the
        assembler's — which does not read the listing at all unless the day is
        the user's today. Each resolves the local date through the same pair
        underneath, so the two cannot disagree, and having the rendering half
        here is what makes "a past-day prompt carries no forward-looking
        material" assertable without a database.

        **What is absent is stated, because silence would mislead.** The listing
        has already dropped done, cancelled and lapsed tasks, so a model handed
        the survivors alone would reasonably read them as everything the user
        has on. Saying so also stops it describing a quiet week as an idle one.

        An empty week contributes nothing rather than an empty heading, the
        stance :meth:`_build_agenda` already takes and for the same reason.

        The overflow sentence below deliberately stays a copy of the agenda's
        rather than being lifted alongside :func:`_with_people`. That helper is
        one concept in two places; this is two sentences that share a shape —
        what is left out of an agenda is *events on this day*, and what is left
        out here is *tasks due in this window*. Parameterising the noun and the
        phrase would leave a template neither caller could read.
        """
        upcoming = summary_input.upcoming_tasks
        if temporal_context != "Today" or upcoming is None or not upcoming.tasks:
            return ""

        shown = upcoming.tasks[:MAX_TASK_ENTRIES]
        omitted = len(upcoming.tasks) - len(shown)

        lines = [
            "## Tasks Due Soon",
            "The user's outstanding commitments, soonest first, due between today "
            f"and {upcoming.window.last_day:%d %b} — the next "
            f"{upcoming.window.days_ahead} days.",
            "Tasks already done, cancelled or lapsed are deliberately absent, so "
            "every line below is still outstanding.",
        ]
        lines.extend(
            cls._task_line(model, upcoming.window.first_day) for model in shown
        )
        if omitted:
            lines.append(
                f"({omitted} further tasks due in this window are not listed; the "
                f"list above is capped at {MAX_TASK_ENTRIES}.)"
            )
        return "\n".join(lines)

    @classmethod
    def _task_line(cls, model: TaskReadModel, today: date) -> str:
        """One commitment as a single line.

        **No timezone is named and none is needed.** ``TaskJournalRef.date`` is
        a date the read service already resolved in the acting user's zone, so
        unlike an agenda entry — whose clock columns are the *event's* local
        time — there is no second zone here for a reader to be misled by. Do not
        "fix" this by qualifying it.

        The relative label is not decoration: the model is being asked to notice
        what needs preparing, and a bare ``30 Apr`` makes it do date arithmetic
        against a system time several sections earlier to find out whether that
        is urgent.
        """
        parts = [
            f"Due {model.due_journal.date:%d %b} "
            f"({cls._relative_day(model.due_journal.date, today)}):",
            model.task.text,
            f'(in "{model.due_journal.title}")',
        ]

        people = _with_people(
            [contact.display_name for contact in model.contacts], MAX_TASK_CONTACTS
        )
        if people:
            parts.append(people)

        return f"- {' '.join(parts)}"

    @staticmethod
    def _relative_day(due: date, today: date) -> str:
        """How far off a due date is, in the words a person would use."""
        days = (due - today).days
        if days <= 0:
            # A forward window starts today, so a negative gap is unreachable
            # through the listing; reading it as "today" beats inventing a
            # phrase for a case that would mean the window was built wrong.
            return "today"
        if days == 1:
            return "tomorrow"
        return f"in {days} days"

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
