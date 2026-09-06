"""Unit tests for DailySummaryPromptBuilder."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from core_shared.models.contacts.important_date_types import ImportantDateType
from core_shared.models.tasks import (
    Task,
    TaskContactRef,
    TaskJournalRef,
    TaskReadModel,
    TaskStatus,
    UpcomingTasks,
    build_task_read_model,
    upcoming_window,
)

from app.core.contacts.models.upcoming_dates import upcoming_dates_window
from app.core.journal.models.agenda import AgendaEntry, AgendaParticipant
from app.core.journal.services.daily_summary_models import (
    DailySummaryInput,
    DailySummaryJournalEntry,
)
from app.core.journal.services.daily_summary_prompt_builder import (
    MAX_AGENDA_ENTRIES,
    MAX_AGENDA_PARTICIPANTS,
    MAX_CONTENT_LENGTH,
    MAX_DATE_ENTRIES,
    MAX_TASK_CONTACTS,
    MAX_TASK_ENTRIES,
    MAX_TASK_TEXT_LENGTH,
    DailySummaryPromptBuilder,
)
from tests.unit.journal.upcoming_date_doubles import (
    DEFAULT_DATE_WINDOW,
    coming_up,
    occurring,
    stored_date,
)

# Both daily-summary suites are pure and mock-backed, but neither carried the
# marker CI selects on, so none of their tests ran there. Added with the phase
# that puts new assertions in them: a test outside the selection is a test that
# does not run.
pytestmark = pytest.mark.unit


def _make_input(**overrides: object) -> DailySummaryInput:
    """Helper to create a DailySummaryInput with sensible defaults."""
    defaults: dict[str, object] = {
        "user_id": "user123",
        "summary_date": date(2026, 4, 27),
        "journals": [],
        "journal_count": 0,
        "event_count": 0,
        "contact_names": [],
        "mood_values": [],
        "previous_summary": None,
    }
    defaults.update(overrides)
    return DailySummaryInput(**defaults)  # type: ignore[arg-type]


class TestDailySummaryPromptBuilder:
    """Test prompt construction."""

    def test_basic_prompt_structure(self) -> None:
        """Prompt includes system instructions, overview, and output format."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "summarising a user's day" in prompt
        assert "Day Overview" in prompt
        assert "Output Format" in prompt
        assert "summary_text" in prompt

    def test_system_instructions_direct_tool_use(self) -> None:
        """The prompt tells the model to research contact context via the tools."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "get_contact_journals" in prompt
        assert "recent meetings" in prompt
        assert "remember or action" in prompt

    def test_grounding_rule_names_every_source_it_was_given(self) -> None:
        """One grounding rule, listing all of them.

        Tool results have always counted alongside the journals; the agenda
        joined them when it became an input, and the week's tasks joined them
        next. Each is named in the *same* sentence rather than a second one,
        because two grounding rules that list different sources are a
        contradiction the model is free to resolve either way — and resolving it
        the wrong way discards whichever group is newest.

        The superseded forms are asserted absent, so widening the sentence again
        cannot leave a narrower claim standing beside it.
        """
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert (
            "not present in the journals, the agenda, the tasks, the upcoming "
            "contact dates or the tool results" in prompt
        )
        assert "the tasks or the tool results you were given" not in prompt
        assert "not present in the journals, the agenda or the tool" not in prompt
        assert "not present in the journals or tool results" not in prompt

    def test_output_format_requests_two_paragraphs(self) -> None:
        """The output format asks for two paragraphs, not 1-3 sentences."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "two paragraphs" in prompt
        assert "blank line" in prompt
        assert "1-3 sentences" not in prompt

    def test_day_overview_includes_date(self) -> None:
        """The overview section contains the ISO date."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(summary_date=date(2026, 4, 27)))

        assert "2026-04-27" in prompt

    def test_day_overview_includes_counts(self) -> None:
        """The overview section contains journal and event counts."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(journal_count=3, event_count=2))

        assert "Journal count: 3" in prompt
        assert "Event count: 2" in prompt

    def test_day_overview_includes_contacts(self) -> None:
        """Contacts are listed when present."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(contact_names=["Alice", "Bob", "Alice"]))

        # Deduplicated and sorted
        assert "Alice" in prompt
        assert "Bob" in prompt

    def test_day_overview_includes_mood_average(self) -> None:
        """Mood average is computed and shown."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(mood_values=[6, 8, 7]))

        assert "Average mood: 7.0" in prompt

    def test_journal_entries_section(self) -> None:
        """Journal entries are rendered with title and content."""
        entries = [
            DailySummaryJournalEntry(
                title="Morning Run",
                content="Ran 5km in the park.",
                types=["FITNESS", "NOTE"],
                contact_names=["Alice"],
                mood_value=8,
                energy_level=7,
            ),
            DailySummaryJournalEntry(
                title="Team Meeting",
                content="Discussed Q2 goals.",
                types=["EVENT"],
            ),
        ]
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(journals=entries))

        assert "Entry 1: Morning Run" in prompt
        assert "Ran 5km in the park." in prompt
        assert "Types: FITNESS, NOTE" in prompt
        assert "Contacts: Alice" in prompt
        assert "Mood: 8" in prompt
        assert "Energy: 7" in prompt
        assert "Entry 2: Team Meeting" in prompt
        assert "Discussed Q2 goals." in prompt

    def test_content_truncation(self) -> None:
        """Long content is truncated."""
        long_content = "x" * (MAX_CONTENT_LENGTH + 100)
        entries = [
            DailySummaryJournalEntry(
                title="Verbose Entry",
                content=long_content,
            ),
        ]
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(journals=entries))

        # Content should be truncated with ellipsis
        assert "..." in prompt
        # Original full content should not appear
        assert long_content not in prompt

    def test_empty_journals_omits_entries_section(self) -> None:
        """No 'Journal Entries' heading when there are no journals."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(journals=[]))

        assert "Journal Entries" not in prompt

    def test_previous_summary_included(self) -> None:
        """Previous summary is included when present."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(
            _make_input(previous_summary="Yesterday was a quiet day.")
        )

        assert "Previous Summary" in prompt
        assert "Yesterday was a quiet day." in prompt

    def test_no_previous_summary_section_when_none(self) -> None:
        """Previous summary section is omitted when None."""
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input(previous_summary=None))

        assert "Previous Summary" not in prompt

    def test_prompt_includes_current_system_time_and_temporal_context(self) -> None:
        """Prompt includes current time and past/today/future context."""
        builder = DailySummaryPromptBuilder()

        from datetime import UTC, datetime, timedelta

        now_time = datetime.now(tz=UTC)
        now_date = now_time.date()

        # Test Past
        prompt_past = builder.build(
            _make_input(summary_date=now_date - timedelta(days=1)), now=now_time
        )
        assert "Current System Time" in prompt_past
        assert "UTC" in prompt_past
        assert "(Past)" in prompt_past

        # Test Today
        prompt_today = builder.build(_make_input(summary_date=now_date), now=now_time)
        assert "(Today)" in prompt_today

        # Test Future
        prompt_future = builder.build(
            _make_input(summary_date=now_date + timedelta(days=1)), now=now_time
        )
        assert "(Future)" in prompt_future

    def test_current_time_uses_user_timezone(self) -> None:
        """Current system time is rendered in the user's timezone with a label."""
        from datetime import UTC, datetime

        builder = DailySummaryPromptBuilder()
        now_time = datetime(2026, 6, 7, 0, 0, 0, tzinfo=UTC)

        prompt = builder.build(
            _make_input(summary_date=datetime(2026, 6, 7).date()),
            now=now_time,
            timezone="Australia/Sydney",
        )

        # Sydney is UTC+10 in June: midnight UTC -> 10:00 local
        assert "2026-06-07 10:00:00" in prompt
        assert "AEST" in prompt
        assert "+10:00" in prompt
        assert "UTC" not in prompt.replace("(UTC+10:00)", "")

    def test_temporal_context_uses_user_timezone_date(self) -> None:
        """Temporal context is computed against the date in the user's timezone."""
        from datetime import UTC, datetime

        builder = DailySummaryPromptBuilder()
        # 23:00 UTC on the 6th is already the 7th (09:00) in Sydney.
        now_time = datetime(2026, 6, 6, 23, 0, 0, tzinfo=UTC)

        prompt = builder.build(
            _make_input(summary_date=datetime(2026, 6, 7).date()),
            now=now_time,
            timezone="Australia/Sydney",
        )
        # In Sydney it is the 7th, so summarising the 7th is "Today".
        assert "(Today)" in prompt


class TestPromptSeriesLine:
    """Series membership is rendered per entry when present."""

    def test_entry_section_includes_series_line(self) -> None:
        builder = DailySummaryPromptBuilder()
        summary_input = DailySummaryInput(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            journals=[
                DailySummaryJournalEntry(
                    title="Physio session",
                    content="Knee exercises",
                    types=["EVENT"],
                    series_names=["Physio appointments"],
                )
            ],
            journal_count=1,
        )

        prompt = builder.build(summary_input)

        assert "Series: Physio appointments" in prompt

    def test_entry_without_series_omits_line(self) -> None:
        builder = DailySummaryPromptBuilder()
        summary_input = DailySummaryInput(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            journals=[
                DailySummaryJournalEntry(
                    title="One-off note",
                    content="Nothing recurring",
                )
            ],
            journal_count=1,
        )

        prompt = builder.build(summary_input)

        assert "Series:" not in prompt


_NOW = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)
_TODAY = date(2026, 4, 27)


def _agenda_entry(**overrides: object) -> AgendaEntry:
    """An agenda entry with sensible defaults: a timed, uncancelled event."""
    defaults: dict[str, object] = {
        "journal_id": 1,
        "title": "Design review",
        "is_all_day": False,
        "starts_at": datetime(2026, 4, 27, 9, 0, tzinfo=UTC),
        "ends_at": datetime(2026, 4, 27, 9, 30, tzinfo=UTC),
        "start_time": time(9, 0),
        "end_time": time(9, 30),
    }
    defaults.update(overrides)
    return AgendaEntry(**defaults)  # type: ignore[arg-type]


class TestTheAgendaIsCurrentDayOnly:
    """Forward-looking material belongs to today and to no other day."""

    def test_agenda_section_present_for_today(self) -> None:
        """Today's prompt carries the day's events, times, locations and people."""
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(
            location="Level 3 boardroom",
            participants=(AgendaParticipant(contact_id=7, name="Alice Smith"),),
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]), now=_NOW
        )

        assert "Today's Agenda" in prompt
        assert "Design review" in prompt
        assert "09:00-09:30" in prompt
        assert "Level 3 boardroom" in prompt
        assert "Alice Smith" in prompt

    def test_agenda_absent_for_a_past_day(self) -> None:
        """A past day describes that day, not what was scheduled on it now."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY - timedelta(days=1), agenda=[_agenda_entry()]
            ),
            now=_NOW,
        )

        assert "Today's Agenda" not in prompt
        assert "Design review" not in prompt

    def test_agenda_absent_for_a_future_day(self) -> None:
        """The rule is "the current day", not "today or later"."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY + timedelta(days=1), agenda=[_agenda_entry()]
            ),
            now=_NOW,
        )

        assert "Today's Agenda" not in prompt
        assert "Design review" not in prompt

    def test_no_entries_adds_no_heading(self) -> None:
        """A day with nothing scheduled gains no empty section."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(_make_input(summary_date=_TODAY, agenda=[]), now=_NOW)

        assert "Today's Agenda" not in prompt


class TestHowAnAgendaEntryReads:
    """One entry's rendering: times, cancellation and the caps."""

    def test_all_day_entry_renders_all_day(self) -> None:
        """An all-day item is true of the whole day, not a thing at 00:00."""
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(
            title="Public holiday",
            is_all_day=True,
            start_time=None,
            end_time=None,
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]), now=_NOW
        )

        assert "All day: Public holiday" in prompt

    def test_timed_entry_without_clock_times_renders_no_time(self) -> None:
        """No clock columns means no time — never one invented from the instant."""
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(title="Mystery meeting", start_time=None, end_time=None)

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]), now=_NOW
        )

        assert "- Mystery meeting" in prompt
        assert "All day" not in prompt

    def test_cancelled_entry_is_marked(self) -> None:
        """A cancelled event is never presented as something the user is doing."""
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(title="Dentist", is_cancelled=True)

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]), now=_NOW
        )

        assert "[CANCELLED]" in prompt
        assert "did not go ahead" in prompt

    def test_entry_cap_states_the_overflow(self) -> None:
        """A busy day is capped, and the prompt says so rather than truncating."""
        builder = DailySummaryPromptBuilder()
        entries = [
            _agenda_entry(journal_id=i, title=f"Event-{i:02d}")
            for i in range(MAX_AGENDA_ENTRIES + 5)
        ]

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=entries), now=_NOW
        )

        assert f"Event-{MAX_AGENDA_ENTRIES - 1:02d}" in prompt
        assert f"Event-{MAX_AGENDA_ENTRIES:02d}" not in prompt
        assert "5 further events" in prompt

    def test_participant_cap_states_the_overflow(self) -> None:
        """A large invite list is capped per entry, and counted rather than cut."""
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(
            participants=tuple(
                AgendaParticipant(contact_id=i, name=f"Person-{i:02d}")
                for i in range(MAX_AGENDA_PARTICIPANTS + 2)
            )
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]), now=_NOW
        )

        assert f"Person-{MAX_AGENDA_PARTICIPANTS - 1:02d}" in prompt
        assert f"Person-{MAX_AGENDA_PARTICIPANTS:02d}" not in prompt
        assert "and 2 more" in prompt


class TestToneAndSafetyInstructions:
    """The constraints the specification says matter more now."""

    def test_do_not_restate_instruction_present(self) -> None:
        """The summary's value is connecting the sections, not repeating them."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(_make_input())

        assert "item by item" in prompt
        assert "restate" in prompt

    def test_the_local_timezone_claim_admits_the_exception(self) -> None:
        """The blanket claim contradicted the agenda's own foreign-zone rows.

        Saying every time is the user's local time, and then printing
        ``09:00 (America/New_York)``, tells the model two incompatible things
        about the same value.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(_make_input())

        assert "unless a different timezone is named beside them" in prompt
        assert (
            "All times and dates are shown in the user's local timezone" not in prompt
        )

    def test_existing_tone_constraints_retained(self) -> None:
        """Adding inputs must not cost the constraints already in the prompt."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(_make_input())

        assert "practical and descriptive rather than speculative" in prompt
        assert "Do not invent information" in prompt
        assert "Do not rewrite the journal record" in prompt


class TestAnEventInAnotherTimezone:
    """The clock columns are the *event's* local time, not the reader's.

    Migration 0045 derives ``start_time``/``end_time`` ``AT TIME ZONE
    jci.timezone``, so a 09:00 New York meeting stores ``09:00`` for a Sydney
    user too. Rendering it bare tells the model the user has a morning
    appointment — the failure the API design document names.

    Naming the zone is not enough either, because the entry reached this agenda
    by *instant* overlap and its own local date can be the neighbouring one. So
    a foreign-zone entry leads with the reader's clock time and carries its own
    behind it.
    """

    def test_the_readers_time_leads_and_the_events_own_follows(self) -> None:
        """A real 09:00 New York meeting, as a Sydney reader sees it.

        The instant and the clock column agree the way migration 0045
        guarantees: 09:00 EDT is 13:00 UTC, which is 23:00 in Sydney.
        """
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(
            title="New York sync",
            timezone="America/New_York",
            starts_at=datetime(2026, 4, 27, 13, 0, tzinfo=UTC),
            ends_at=datetime(2026, 4, 27, 13, 30, tzinfo=UTC),
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]),
            now=_NOW,
            timezone="Australia/Sydney",
        )

        assert "23:00-23:30 (09:00-09:30 America/New_York): New York sync" in prompt

    def test_an_event_whose_own_date_is_the_day_before(self) -> None:
        """23:00 on a New York Monday sits in a Sydney user's Tuesday.

        The clock column says 23:00 and the zone says New York, but the event is
        happening at 14:00 on the reader's Tuesday afternoon. Rendering only the
        event's own clock would put a late-night commitment on a day that has
        none — the ambiguity naming the zone alone does not resolve.
        """
        builder = DailySummaryPromptBuilder()
        entry = AgendaEntry(
            journal_id=9,
            title="Late call",
            is_all_day=False,
            # Monday 23:00 in New York (EDT, -4) is Tuesday 03:00 UTC.
            starts_at=datetime(2026, 4, 28, 3, 0, tzinfo=UTC),
            ends_at=datetime(2026, 4, 28, 4, 0, tzinfo=UTC),
            start_time=time(23, 0),
            end_time=time(0, 0),
            timezone="America/New_York",
        )

        prompt = builder.build(
            _make_input(summary_date=date(2026, 4, 28), agenda=[entry]),
            now=datetime(2026, 4, 28, 3, 0, tzinfo=UTC),
            timezone="Australia/Sydney",
        )

        # Tuesday 03:00 UTC is Tuesday 13:00 in Sydney (AEST, +10).
        assert "13:00-14:00 (23:00-00:00 America/New_York): Late call" in prompt

    def test_the_users_own_zone_is_not_named(self) -> None:
        """Naming the zone on every row would make the exception invisible."""
        builder = DailySummaryPromptBuilder()
        # 09:00 Sydney on the 27th is 23:00 UTC on the 26th.
        entry = _agenda_entry(
            timezone="Australia/Sydney",
            starts_at=datetime(2026, 4, 26, 23, 0, tzinfo=UTC),
            ends_at=datetime(2026, 4, 26, 23, 30, tzinfo=UTC),
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]),
            now=_NOW,
            timezone="Australia/Sydney",
        )

        assert "09:00-09:30: Design review" in prompt
        assert "(Australia/Sydney)" not in prompt

    def test_a_missing_zone_reads_as_utc_and_is_named_when_it_differs(self) -> None:
        """A null zone means UTC, which is still not a Sydney user's clock."""
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(timezone=None)

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]),
            now=_NOW,
            timezone="Australia/Sydney",
        )

        # 09:00-09:30 UTC is 19:00-19:30 in Sydney (AEST, +10 in late April).
        assert "19:00-19:30 (09:00-09:30 UTC): Design review" in prompt

    def test_an_all_day_entry_names_no_zone(self) -> None:
        """An all-day event happens on a date; there is no clock value to qualify."""
        builder = DailySummaryPromptBuilder()
        entry = _agenda_entry(
            title="Public holiday",
            is_all_day=True,
            start_time=None,
            end_time=None,
            timezone="America/New_York",
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]),
            now=_NOW,
            timezone="Australia/Sydney",
        )

        assert "All day: Public holiday" in prompt
        assert "America/New_York" not in prompt

    def test_the_section_warns_that_a_named_zone_is_not_comparable(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[_agenda_entry()]), now=_NOW
        )

        assert "Every time below is the user's own local time" in prompt


class TestAMultiDayEvent:
    """A timed event can begin before this day and end after it.

    The agenda matches timed events by overlap precisely so a multi-day trip
    appears on the days in the middle of it, and for those the two clock values
    belong to different dates.
    """

    def test_a_span_leaving_the_day_carries_its_dates(self) -> None:
        """Otherwise a Monday-to-Wednesday trip reads as a Tuesday appointment."""
        builder = DailySummaryPromptBuilder()
        entry = AgendaEntry(
            journal_id=4,
            title="Bushwalking trip",
            is_all_day=False,
            starts_at=datetime(2026, 4, 27, 9, 0, tzinfo=UTC),
            ends_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
            start_time=time(9, 0),
            end_time=time(9, 0),
        )

        prompt = builder.build(
            _make_input(summary_date=date(2026, 4, 28), agenda=[entry]),
            now=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        )

        assert "27 Apr 09:00 - 29 Apr 09:00: Bushwalking trip" in prompt
        # The bare form would read as an event of no duration at all.
        assert "09:00-09:00" not in prompt

    def test_a_span_inside_the_day_stays_terse(self) -> None:
        """Dates on every row would bury the ones that need them."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[_agenda_entry()]), now=_NOW
        )

        assert "09:00-09:30: Design review" in prompt
        assert "Apr" not in prompt.split("## Today's Agenda")[1]


def _task(
    task_id: int,
    *,
    due_date: date,
    text: str = "book the venue",
    journal_title: str = "Monday standup",
    contacts: tuple[TaskContactRef, ...] = (),
) -> TaskReadModel:
    """One assembled task, built the way the read service builds one.

    Through ``build_task_read_model`` so ``lapse_reason`` is derived rather than
    hand-set, the reasoning ``tests/unit/tasks/test_task_upcoming_window`` gives
    for its own helper.
    """
    due_journal = TaskJournalRef(
        id=900 + task_id, title=journal_title, date=due_date, cancelled=False
    )
    return build_task_read_model(
        task=Task(
            id=task_id,
            user_id="user123",
            text=text,
            creating_journal_id=1,
            due_journal_id=due_journal.id,
        ),
        creating_journal=TaskJournalRef(
            id=1, title="where it arose", date=_TODAY, cancelled=False
        ),
        due_journal=due_journal,
        intermediate_journals=[],
        contacts=contacts,
        today=_TODAY,
    )


def _due_soon(*tasks: TaskReadModel, days_ahead: int = 7) -> UpcomingTasks:
    """The listing's answer for the current day, window and all."""
    return UpcomingTasks(window=upcoming_window(_TODAY, days_ahead), tasks=tasks)


class TestUpcomingTasksSection:
    """The week's commitments, on the current day's prompt and no other."""

    def test_todays_prompt_carries_the_task_and_its_journal(self) -> None:
        """Text, due date and the journal it is due in all reach the model."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY)),
            ),
            now=_NOW,
        )

        assert "## Tasks Due Soon" in prompt
        assert "Due 27 Apr (today): book the venue" in prompt
        assert '(in "Monday standup")' in prompt

    def test_linked_contacts_travel_with_the_task(self) -> None:
        """The connective work needs the person, not just the commitment."""
        builder = DailySummaryPromptBuilder()
        task = _task(
            1,
            due_date=_TODAY,
            contacts=(
                TaskContactRef(id=5, display_name="Alice Smith", photo_url=None),
                TaskContactRef(id=6, display_name="Bob Jones", photo_url=None),
            ),
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_tasks=_due_soon(task)),
            now=_NOW,
        )

        assert "with Alice Smith, Bob Jones" in prompt

    def test_a_task_with_no_contacts_has_no_dangling_with(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY)),
            ),
            now=_NOW,
        )

        assert "book the venue with" not in prompt
        assert "with \n" not in prompt

    def test_due_dates_are_labelled_relative_to_today(self) -> None:
        """A date alone makes the model do the arithmetic; the label does not."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(
                    _task(1, due_date=_TODAY, text="today's"),
                    _task(2, due_date=_TODAY + timedelta(days=1), text="tomorrow's"),
                    _task(3, due_date=_TODAY + timedelta(days=3), text="later"),
                ),
            ),
            now=_NOW,
        )

        assert "Due 27 Apr (today): today's" in prompt
        assert "Due 28 Apr (tomorrow): tomorrow's" in prompt
        assert "Due 30 Apr (in 3 days): later" in prompt

    def test_the_section_states_the_window_it_describes(self) -> None:
        """The window travels with the tasks so the prompt can name it."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY)),
            ),
            now=_NOW,
        )

        assert "the next 7 days" in prompt
        assert "04 May" in prompt

    def test_the_section_says_what_is_deliberately_absent(self) -> None:
        """Otherwise silence reads as "this is everything the user has on"."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY)),
            ),
            now=_NOW,
        )

        assert "done, cancelled or lapsed" in prompt

    def test_task_cap_states_the_overflow(self) -> None:
        """A crowded week is capped, and the prompt says so rather than cutting."""
        builder = DailySummaryPromptBuilder()
        tasks = [
            _task(i, due_date=_TODAY, text=f"Task-{i:02d}")
            for i in range(MAX_TASK_ENTRIES + 3)
        ]

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_tasks=_due_soon(*tasks)),
            now=_NOW,
        )

        assert f"Task-{MAX_TASK_ENTRIES - 1:02d}" in prompt
        assert f"Task-{MAX_TASK_ENTRIES:02d}" not in prompt
        assert "3 further tasks" in prompt

    def test_contact_cap_states_the_overflow(self) -> None:
        """A widely-shared commitment is capped per task, and counted."""
        builder = DailySummaryPromptBuilder()
        task = _task(
            1,
            due_date=_TODAY,
            contacts=tuple(
                TaskContactRef(id=i, display_name=f"Person-{i:02d}", photo_url=None)
                for i in range(MAX_TASK_CONTACTS + 2)
            ),
        )

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_tasks=_due_soon(task)),
            now=_NOW,
        )

        assert f"Person-{MAX_TASK_CONTACTS - 1:02d}" in prompt
        assert f"Person-{MAX_TASK_CONTACTS:02d}" not in prompt
        assert "and 2 more" in prompt


class TestNoForwardLookingTasksOnAnyOtherDay:
    """A past-day summary describes that day; a future one is not today either."""

    def test_a_past_day_carries_no_task_material(self) -> None:
        """The same input, judged a day late, renders none of it."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY - timedelta(days=1),
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY)),
            ),
            now=_NOW,
        )

        assert "## Tasks Due Soon" not in prompt
        assert "book the venue" not in prompt

    def test_a_future_day_carries_no_task_material(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY + timedelta(days=1),
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY)),
            ),
            now=_NOW,
        )

        assert "## Tasks Due Soon" not in prompt
        assert "book the venue" not in prompt


class TestAQuietWeekAddsNoHeading:
    """An empty heading reads as a section the model must account for."""

    def test_an_empty_window_adds_no_heading(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_tasks=_due_soon()), now=_NOW
        )

        assert "## Tasks Due Soon" not in prompt

    def test_a_day_that_gathered_nothing_adds_no_heading(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_tasks=None), now=_NOW
        )

        assert "## Tasks Due Soon" not in prompt


class TestTheToneInstructionsCoverEveryInputGroup:
    """A new input group widens an existing rule; it never gets a second one.

    Renamed from *…CoverTasks* by the contact-dates phase rather than joined by
    a sibling class, for the reason the rule itself states: a second assertion
    beside a narrower one leaves the narrow claim standing. The superseded forms
    are asserted absent here too, so the next widening cannot half-happen.
    """

    def test_the_grounding_rule_names_every_group(self) -> None:
        """Two grounding sentences listing different sources contradict."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(_make_input(summary_date=_TODAY), now=_NOW)

        assert (
            "Do not invent information not present in the journals, the agenda, "
            "the tasks, the upcoming contact dates or the tool results you were "
            "given." in prompt
        )
        assert "the tasks or the tool results you were given" not in prompt

    def test_the_do_not_restate_rule_names_every_group(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(_make_input(summary_date=_TODAY), now=_NOW)

        assert (
            "Do not restate the day's agenda, journals, tasks, upcoming dates or "
            "other listed material item by item" in prompt
        )
        assert "the day's agenda, journals, tasks or other listed" not in prompt
        assert "the day's agenda, journals or other listed" not in prompt


class TestAnUnboundedTaskTextIsCapped:
    """``tasks.text`` is deliberately unbounded, so the prompt bounds it.

    Capping the *number* of tasks does nothing about the size of one, and a
    single arbitrarily large row would push the whole request past the model's
    limit — failing that day's summary outright rather than degrading it.
    """

    def test_a_long_text_is_truncated_and_marked(self) -> None:
        builder = DailySummaryPromptBuilder()
        text = "x" * (MAX_TASK_TEXT_LENGTH + 50) + "TAIL"

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY, text=text)),
            ),
            now=_NOW,
        )

        assert "x" * MAX_TASK_TEXT_LENGTH + "..." in prompt
        assert "TAIL" not in prompt

    def test_a_text_at_the_limit_is_left_alone(self) -> None:
        """The boundary from the other side, so the cap cannot be off by one."""
        builder = DailySummaryPromptBuilder()
        text = "y" * MAX_TASK_TEXT_LENGTH

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY, text=text)),
            ),
            now=_NOW,
        )

        assert text in prompt
        assert text + "..." not in prompt

    def test_an_ordinary_task_is_untouched(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_tasks=_due_soon(_task(1, due_date=_TODAY)),
            ),
            now=_NOW,
        )

        assert "book the venue (in" in prompt
        assert "..." not in prompt


# A day already behind ``_TODAY``, so the past-day guard fires for it.
_YESTERDAY = date(2026, 4, 26)


def _resolved(
    task_id: int,
    *,
    status: TaskStatus = TaskStatus.NOT_DONE,
    text: str = "book the venue",
    journal_title: str = "Site visit",
    cancelled: bool = False,
    contacts: tuple[TaskContactRef, ...] = (),
) -> TaskReadModel:
    """One task due on the past day, judged from ``_TODAY``.

    Kept apart from ``_task`` above rather than folded into it: that helper
    always builds a *not-done* task judged on its own due date, which is exactly
    what a forward window holds and exactly what a resolution never is. Here the
    status varies and ``today`` is deliberately later than the due date, so
    ``build_task_read_model`` derives the lapse the way production does.
    """
    due_journal = TaskJournalRef(
        id=800 + task_id, title=journal_title, date=_YESTERDAY, cancelled=cancelled
    )
    return build_task_read_model(
        task=Task(
            id=task_id,
            user_id="user123",
            text=text,
            creating_journal_id=1,
            due_journal_id=due_journal.id,
            status=status,
        ),
        creating_journal=TaskJournalRef(
            id=1, title="where it arose", date=_YESTERDAY, cancelled=False
        ),
        due_journal=due_journal,
        intermediate_journals=[],
        contacts=contacts,
        today=_TODAY,
    )


class TestPastDayTasksSection:
    """What was due on the day, and how each commitment stands now."""

    def test_a_past_prompt_carries_the_task_and_its_journal(self) -> None:
        """The commitment, the journal it was due in, and nothing forward-looking."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[_resolved(1)]),
            now=_NOW,
        )

        assert "## Tasks Due On This Day" in prompt
        assert "book the venue" in prompt
        assert '(in "Site visit")' in prompt

    def test_linked_contacts_travel_with_the_task(self) -> None:
        """The person is half of what makes a resolution worth reporting."""
        builder = DailySummaryPromptBuilder()
        task = _resolved(
            1,
            contacts=(
                TaskContactRef(id=5, display_name="Alice Smith", photo_url=None),
                TaskContactRef(id=6, display_name="Bob Jones", photo_url=None),
            ),
        )

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[task]), now=_NOW
        )

        assert "with Alice Smith, Bob Jones" in prompt

    def test_the_section_says_the_statuses_are_current(self) -> None:
        """The phase's headline consequence, stated to the model itself.

        Without it a model reading "done" beside a past date would narrate the
        user finishing the task *on the day*, which the data does not say and
        which is false whenever it was finished later.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[_resolved(1)]),
            now=_NOW,
        )

        assert "how each one stands now" in prompt
        assert "rather than a reconstruction of the day" in prompt

    def test_no_due_date_is_repeated_on_the_line(self) -> None:
        """The heading already names the day; the journal is what distinguishes.

        The forward-looking section carries a date and a relative label because
        its tasks are spread over a week. These are all due on the day the
        prompt is about, so the same treatment would be noise.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[_resolved(1)]),
            now=_NOW,
        )

        assert "Due 26 Apr" not in prompt
        assert "(today)" not in prompt


class TestHowEachResolutionReads:
    """The four answers, each worded so a model cannot conflate two of them."""

    def test_a_completed_task_reads_as_done(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_YESTERDAY,
                past_day_tasks=[_resolved(1, status=TaskStatus.DONE)],
            ),
            now=_NOW,
        )

        assert "book the venue" in prompt
        assert "— done" in prompt

    def test_a_cancelled_task_reads_as_cancelled(self) -> None:
        """The user called it off, which is not the same as never doing it."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_YESTERDAY,
                past_day_tasks=[_resolved(1, status=TaskStatus.CANCELLED)],
            ),
            now=_NOW,
        )

        assert "— cancelled" in prompt
        assert "still not done" not in prompt

    def test_an_unfinished_task_reads_as_lapsed_because_the_day_passed(self) -> None:
        """The ordinary past-day verdict, and the most common one."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[_resolved(1)]),
            now=_NOW,
        )

        assert "— still not done; lapsed, the day passed" in prompt

    def test_a_cancelled_due_journal_is_named_as_the_cause(self) -> None:
        """The other lapse is different news and is worded differently.

        "The day went by" and "the meeting was called off" ask the user for
        different things, which is why the rule returns a reason rather than a
        boolean — and why this prompt spends a clause on which one it was.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_YESTERDAY, past_day_tasks=[_resolved(1, cancelled=True)]
            ),
            now=_NOW,
        )

        assert "— still not done; lapsed, its due journal was cancelled" in prompt

    def test_every_resolution_can_appear_in_one_day(self) -> None:
        """A real day resolves several ways at once, and each keeps its own line."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_YESTERDAY,
                past_day_tasks=[
                    _resolved(1, status=TaskStatus.DONE, text="pack the rope"),
                    _resolved(2, status=TaskStatus.CANCELLED, text="call the council"),
                    _resolved(3, text="return the key"),
                ],
            ),
            now=_NOW,
        )

        assert "- pack the rope" in prompt
        assert "- call the council" in prompt
        assert "- return the key" in prompt
        assert prompt.count("— done") == 1
        assert prompt.count("— cancelled") == 1
        assert prompt.count("— still not done") == 1


class TestNoResolutionsOnAnyOtherDay:
    """A resolution belongs to a day that has been, and to no other."""

    def test_the_current_day_renders_neither_heading_nor_task(self) -> None:
        """Today's commitments are the week's window; two sections would duplicate.

        The input is the same object in both cases, so this can only pass if the
        builder is judging the day rather than the presence of the field.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                past_day_tasks=[_resolved(1, text="a resolved commitment")],
            ),
            now=_NOW,
        )

        assert "## Tasks Due On This Day" not in prompt
        assert "a resolved commitment" not in prompt

    def test_a_future_day_renders_neither_heading_nor_task(self) -> None:
        """Nothing has resolved on a day that has not happened."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=date(2026, 4, 28),
                past_day_tasks=[_resolved(1, text="a resolved commitment")],
            ),
            now=_NOW,
        )

        assert "## Tasks Due On This Day" not in prompt
        assert "a resolved commitment" not in prompt

    def test_a_past_prompt_carries_no_forward_looking_material(self) -> None:
        """The other half of the same rule, asserted from this side.

        A past day is handed both a window and a resolution list here, which no
        assembler would produce — precisely so that the *builder's* guards are
        what the assertion rests on.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_YESTERDAY,
                past_day_tasks=[_resolved(1)],
                upcoming_tasks=_due_soon(
                    _task(9, due_date=_TODAY, text="next week's problem")
                ),
                agenda=[_agenda_entry(title="A scheduled event")],
            ),
            now=_NOW,
        )

        assert "## Tasks Due On This Day" in prompt
        assert "## Tasks Due Soon" not in prompt
        assert "next week's problem" not in prompt
        assert "## Today's Agenda" not in prompt
        assert "A scheduled event" not in prompt


class TestAQuietPastDayAddsNoHeading:
    """A heading with nothing under it reads as a section the model must fill."""

    def test_an_empty_day_adds_no_heading(self) -> None:
        """Gathered and nothing due: a real answer, but not one worth a section."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[]), now=_NOW
        )

        assert "## Tasks Due On This Day" not in prompt

    def test_nothing_gathered_adds_no_heading(self) -> None:
        """``None`` is the assembler saying it never asked."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=None), now=_NOW
        )

        assert "## Tasks Due On This Day" not in prompt


class TestThePastDaysBudget:
    """The same three caps the week's tasks take, because it is the same group."""

    def test_the_entry_cap_states_the_overflow(self) -> None:
        """A pathological day is capped, counted, and never silently shortened."""
        builder = DailySummaryPromptBuilder()
        tasks = [
            _resolved(i, text=f"Commitment-{i:02d}")
            for i in range(MAX_TASK_ENTRIES + 3)
        ]

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=tasks), now=_NOW
        )

        assert f"Commitment-{MAX_TASK_ENTRIES - 1:02d}" in prompt
        assert f"Commitment-{MAX_TASK_ENTRIES:02d}" not in prompt
        assert "3 further tasks" in prompt

    def test_the_contact_cap_states_the_overflow(self) -> None:
        builder = DailySummaryPromptBuilder()
        task = _resolved(
            1,
            contacts=tuple(
                TaskContactRef(id=i, display_name=f"Person-{i:02d}", photo_url=None)
                for i in range(MAX_TASK_CONTACTS + 2)
            ),
        )

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[task]), now=_NOW
        )

        assert f"Person-{MAX_TASK_CONTACTS - 1:02d}" in prompt
        assert f"Person-{MAX_TASK_CONTACTS:02d}" not in prompt
        assert "and 2 more" in prompt

    def test_an_unbounded_task_text_is_capped_here_too(self) -> None:
        """``tasks.text`` is unbounded whichever section renders it.

        The cap on the *list* says nothing about the size of one item, and one
        arbitrarily large row would fail the whole day's summary — a per-day
        outage caused by a single task.
        """
        builder = DailySummaryPromptBuilder()
        task = _resolved(1, text="x" * (MAX_TASK_TEXT_LENGTH + 100))

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=[task]), now=_NOW
        )

        assert "x" * MAX_TASK_TEXT_LENGTH + "..." in prompt
        assert "x" * (MAX_TASK_TEXT_LENGTH + 1) not in prompt


class TestTheOverflowNoteIsSharedByAllFourSections:
    """One sentence, four subjects — the extraction a third copy justified.

    The upcoming-tasks phase deliberately left this duplicated between the
    agenda and the week's tasks, reasoning that parameterising the noun *and*
    the phrase would leave a template neither caller could read. With a third
    caller the noun is the only thing that varies, and these assertions are what
    stop the shared sentence quietly renaming one section's subject. The
    contact-dates phase is the fourth caller and adds nothing but a noun, which
    is the extraction paying off rather than being re-argued.
    """

    def test_the_agenda_counts_events_on_this_day(self) -> None:
        builder = DailySummaryPromptBuilder()
        entries = [
            _agenda_entry(journal_id=i, title=f"Event-{i:02d}")
            for i in range(MAX_AGENDA_ENTRIES + 5)
        ]

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=entries), now=_NOW
        )

        assert (
            f"(5 further events on this day are not listed; the list above is "
            f"capped at {MAX_AGENDA_ENTRIES}.)"
        ) in prompt

    def test_the_week_counts_tasks_due_in_this_window(self) -> None:
        builder = DailySummaryPromptBuilder()
        tasks = [
            _task(i, due_date=_TODAY, text=f"Task-{i:02d}")
            for i in range(MAX_TASK_ENTRIES + 4)
        ]

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_tasks=_due_soon(*tasks)),
            now=_NOW,
        )

        assert (
            f"(4 further tasks due in this window are not listed; the list above "
            f"is capped at {MAX_TASK_ENTRIES}.)"
        ) in prompt

    def test_the_past_day_counts_tasks_due_on_this_day(self) -> None:
        builder = DailySummaryPromptBuilder()
        tasks = [
            _resolved(i, text=f"Commitment-{i:02d}")
            for i in range(MAX_TASK_ENTRIES + 3)
        ]

        prompt = builder.build(
            _make_input(summary_date=_YESTERDAY, past_day_tasks=tasks), now=_NOW
        )

        assert (
            f"(3 further tasks due on this day are not listed; the list above is "
            f"capped at {MAX_TASK_ENTRIES}.)"
        ) in prompt

    def test_the_dates_count_contact_dates_in_this_window(self) -> None:
        builder = DailySummaryPromptBuilder()
        dates = [
            occurring(stored_date(i, month=4, day=29), name=f"Person-{i:02d}")
            for i in range(MAX_DATE_ENTRIES + 2)
        ]

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_dates=coming_up(*dates)),
            now=_NOW,
        )

        assert (
            f"(2 further contact dates in this window are not listed; the list "
            f"above is capped at {MAX_DATE_ENTRIES}.)"
        ) in prompt


_DATE_WINDOW = DEFAULT_DATE_WINDOW

# A window over a 28 February that is not itself a leap day, which is the only
# shape in which the substitution can be observed.
_LEAP_NOW = datetime(2026, 2, 25, 9, 0, tzinfo=UTC)
_LEAP_TODAY = date(2026, 2, 25)
_LEAP_WINDOW = upcoming_dates_window(_LEAP_TODAY)


class TestUpcomingDatesSection:
    """Whose dates are coming up, on the current day's prompt and no other."""

    def test_todays_prompt_carries_the_date_and_whose_it_is(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "## Important Dates Coming Up" in prompt
        assert "Ada Lovelace" in prompt
        assert "29 Apr" in prompt

    def test_the_line_carries_a_relative_label(self) -> None:
        """A bare ``29 Apr`` makes the model do arithmetic to find the urgency."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "(in 2 days)" in prompt

    def test_a_date_landing_today_reads_as_today(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=27, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "(today)" in prompt

    def test_the_section_names_the_window_it_describes(self) -> None:
        """An empty week has no rows to derive the span from, so it travels."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "04 May" in prompt
        assert "the next 7 days" in prompt

    def test_the_section_says_these_are_not_appointments(self) -> None:
        """A recurring anniversary is not something anyone has scheduled.

        Left unsaid, a model reading a date under a heading beside the day's
        agenda will describe a birthday as a commitment on the calendar.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "recurring dates, not appointments" in prompt

    def test_the_read_s_order_is_preserved(self) -> None:
        """Date ascending then importance is the contacts read's, not ours."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=28), name="First Person"),
                    occurring(stored_date(2, month=5, day=1), name="Second Person"),
                ),
            ),
            now=_NOW,
        )

        assert prompt.index("First Person") < prompt.index("Second Person")


class TestHowAnUpcomingDateReads:
    """The type, and the derived years where the precision allows one."""

    def test_a_birthday_with_a_stored_year_turns_an_age(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "Birthday, turns 35" in prompt

    def test_an_anniversary_with_a_stored_year_counts_years(self) -> None:
        """ "Turns 12" is what a person says about a child, not a marriage."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(
                        stored_date(
                            1,
                            month=4,
                            day=29,
                            year=2014,
                            date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
                        )
                    )
                ),
            ),
            now=_NOW,
        )

        assert "Marriage anniversary, 12 years" in prompt
        assert "turns" not in prompt

    def test_a_work_anniversary_reads_as_itself(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(
                        stored_date(
                            1,
                            month=4,
                            day=29,
                            date_type=ImportantDateType.WORK_ANNIVERSARY,
                        )
                    )
                ),
            ),
            now=_NOW,
        )

        assert "Work anniversary" in prompt

    def test_a_first_met_date_reads_as_itself(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(
                        stored_date(
                            1, month=4, day=29, date_type=ImportantDateType.FIRST_MET
                        )
                    )
                ),
            ),
            now=_NOW,
        )

        assert "First met" in prompt

    def test_a_custom_type_reads_as_the_name_the_user_gave_it(self) -> None:
        """The user is the only authority on what a custom date means."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(
                        stored_date(
                            1,
                            month=4,
                            day=29,
                            date_type=ImportantDateType.CUSTOM,
                            custom_date_type_id=7,
                            custom_date_type_name="Sobriety",
                        )
                    )
                ),
            ),
            now=_NOW,
        )

        assert "Sobriety" in prompt
        assert "Custom" not in prompt

    def test_a_date_without_a_stored_year_carries_no_count(self) -> None:
        """``DAY_MONTH`` precision has no year to count from; it degrades."""
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(occurring(stored_date(1, month=4, day=29))),
            ),
            now=_NOW,
        )

        assert "Birthday" in prompt
        assert "turns" not in prompt
        assert "years" not in prompt

    def test_a_leap_day_says_where_it_is_being_observed(self) -> None:
        """The substitution is the flag's whole reason for existing.

        Unsaid, the model tells the user a 29 February birthday is on the 28th.
        """
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_LEAP_TODAY,
                upcoming_dates=coming_up(
                    occurring(
                        stored_date(1, month=2, day=29, year=1992), window=_LEAP_WINDOW
                    ),
                    window=_LEAP_WINDOW,
                ),
            ),
            now=_LEAP_NOW,
        )

        assert "28 Feb" in prompt
        assert "29 February, observed on the 28th this year" in prompt

    def test_an_ordinary_date_carries_no_leap_day_caveat(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY,
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "observed on the 28th" not in prompt


class TestNoUpcomingDatesOnAnyOtherDay:
    """Forward-looking material belongs to today; a past day describes itself."""

    def test_a_past_day_carries_no_upcoming_date_material(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY - timedelta(days=1),
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "## Important Dates Coming Up" not in prompt
        assert "Ada Lovelace" not in prompt

    def test_a_future_day_carries_no_upcoming_date_material(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(
                summary_date=_TODAY + timedelta(days=1),
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        assert "## Important Dates Coming Up" not in prompt
        assert "Ada Lovelace" not in prompt


class TestAQuietWeekOfDatesAddsNoHeading:
    """An empty heading reads as a section the model must account for."""

    def test_an_empty_window_adds_no_heading(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_dates=coming_up()), now=_NOW
        )

        assert "## Important Dates Coming Up" not in prompt

    def test_a_day_that_gathered_nothing_adds_no_heading(self) -> None:
        builder = DailySummaryPromptBuilder()

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_dates=None), now=_NOW
        )

        assert "## Important Dates Coming Up" not in prompt


class TestTheUpcomingDatesBudget:
    """The entry cap the other three groups take, and no text cap.

    There is deliberately no ``MAX_DATE_TEXT_LENGTH``: every string this
    section interpolates is bounded — ``custom_date_types.name`` is a
    ``VARCHAR(100)`` and a display name is composed of at most three of them —
    so unlike ``tasks.text`` no single row here can blow a request.
    """

    def test_the_entry_cap_states_the_overflow(self) -> None:
        builder = DailySummaryPromptBuilder()
        dates = [
            occurring(stored_date(i, month=4, day=29), name=f"Person-{i:02d}")
            for i in range(MAX_DATE_ENTRIES + 3)
        ]

        prompt = builder.build(
            _make_input(summary_date=_TODAY, upcoming_dates=coming_up(*dates)),
            now=_NOW,
        )

        assert f"Person-{MAX_DATE_ENTRIES - 1:02d}" in prompt
        assert f"Person-{MAX_DATE_ENTRIES:02d}" not in prompt
        assert "3 further contact dates" in prompt


class TestTheCountersAreUnchangedByTheDatesSection:
    """The phase's fourth criterion, asserted rather than assumed."""

    def test_the_day_overview_is_byte_identical_with_and_without_dates(self) -> None:
        builder = DailySummaryPromptBuilder()
        without = builder.build(
            _make_input(
                summary_date=_TODAY,
                journal_count=3,
                event_count=2,
                contact_names=["Ada Lovelace"],
                mood_values=[4, 2],
            ),
            now=_NOW,
        )
        with_dates = builder.build(
            _make_input(
                summary_date=_TODAY,
                journal_count=3,
                event_count=2,
                contact_names=["Ada Lovelace"],
                mood_values=[4, 2],
                upcoming_dates=coming_up(
                    occurring(stored_date(1, month=4, day=29, year=1991))
                ),
            ),
            now=_NOW,
        )

        overview = "## Day Overview: 2026-04-27 (Today)\n- Journal count: 3\n- Event count: 2\n- Contacts involved: Ada Lovelace\n- Average mood: 3.0"
        assert overview in without
        assert overview in with_dates
