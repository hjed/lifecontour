"""Unit tests for DailySummaryPromptBuilder."""

from datetime import UTC, date, datetime, time, timedelta

from app.core.journal.models.agenda import AgendaEntry, AgendaParticipant
from app.core.journal.services.daily_summary_models import (
    DailySummaryInput,
    DailySummaryJournalEntry,
)
from app.core.journal.services.daily_summary_prompt_builder import (
    MAX_AGENDA_ENTRIES,
    MAX_AGENDA_PARTICIPANTS,
    MAX_CONTENT_LENGTH,
    DailySummaryPromptBuilder,
)


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
        joined them when it became an input. It is named in the *same* sentence
        rather than a second one, because two grounding rules that list
        different sources are a contradiction the model is free to resolve
        either way — and resolving it the wrong way discards the agenda this
        phase exists to supply.
        """
        builder = DailySummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "not present in the journals, the agenda or the tool results" in prompt
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
        builder = DailySummaryPromptBuilder()
        # 09:00-09:30 UTC is 19:00-19:30 in Sydney (AEST, +10 in late April).
        entry = _agenda_entry(title="New York sync", timezone="America/New_York")

        prompt = builder.build(
            _make_input(summary_date=_TODAY, agenda=[entry]),
            now=_NOW,
            timezone="Australia/Sydney",
        )

        assert "19:00-19:30 (09:00-09:30 America/New_York): New York sync" in prompt

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
        entry = _agenda_entry(timezone="Australia/Sydney")

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
