"""Unit tests for DailySummaryPromptBuilder."""

from datetime import date

from app.core.journal.services.daily_summary_models import (
    DailySummaryInput,
    DailySummaryJournalEntry,
)
from app.core.journal.services.daily_summary_prompt_builder import (
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
