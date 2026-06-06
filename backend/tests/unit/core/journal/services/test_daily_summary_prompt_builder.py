from datetime import UTC, date, datetime

from app.core.journal.services.daily_summary_models import (
    DailySummaryInput,
    DailySummaryJournalEntry,
)
from app.core.journal.services.daily_summary_prompt_builder import (
    DailySummaryPromptBuilder,
)


def test_daily_summary_prompt_builder_timezone_handling():
    # Arrange
    builder = DailySummaryPromptBuilder()

    # Sydney is UTC+10 (or +11 in summer). Let's use a fixed UTC time.
    # We'll set the current UTC time to 14:00. In Sydney (+10), this is 00:00 the NEXT day.
    now_utc = datetime(2025, 1, 1, 14, 0, 0, tzinfo=UTC)

    # So the local time in Sydney is 2025-01-02 01:00:00 (due to summer time +11)
    # Actually Jan 1 in Sydney is +11:00, so 14:00 UTC = 01:00 next day.

    # Let's say the summary is for 2025-01-01
    summary_input = DailySummaryInput(
        user_id="user1",
        summary_date=date(2025, 1, 1),
        timezone="Australia/Sydney",
        journals=[
            DailySummaryJournalEntry(
                title="A journal",
                content="Some content",
                types=["NOTE"],
                contact_names=[],
            )
        ],
        journal_count=1,
        event_count=0,
        contact_names=[],
        mood_values=[],
    )

    # Act
    # We pass the simulated 'now_utc' so the builder knows the current system time
    prompt = builder.build(summary_input, now=now_utc)

    # Assert
    # The prompt should contain the system time formatted in Australia/Sydney
    # 2025-01-01 14:00 UTC is 2025-01-02 01:00 Australia/Sydney
    assert "Current System Time: 2025-01-02 01:00:00 Australia/Sydney" in prompt
    # And because summary_date (2025-01-01) is before the local date (2025-01-02), it should be seen as "Past"
    assert "Day Overview: 2025-01-01 (Past)" in prompt


def test_daily_summary_prompt_builder_fallback_utc():
    # Arrange
    builder = DailySummaryPromptBuilder()

    now_utc = datetime(2025, 1, 1, 14, 0, 0, tzinfo=UTC)

    summary_input = DailySummaryInput(
        user_id="user1",
        summary_date=date(2025, 1, 1),
        timezone="Invalid/Timezone",  # Should fallback to UTC
        journals=[],
        journal_count=0,
        event_count=0,
        contact_names=[],
        mood_values=[],
    )

    # Act
    prompt = builder.build(summary_input, now=now_utc)

    # Assert
    assert "Current System Time: 2025-01-01 14:00:00 UTC" in prompt
    assert "Day Overview: 2025-01-01 (Today)" in prompt
