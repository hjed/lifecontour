from datetime import UTC, datetime
from unittest.mock import patch

from app.core.contacts.services.summary_models import SummaryInput
from app.core.contacts.services.summary_prompt_builder import SummaryPromptBuilder


@patch("app.core.contacts.services.summary_prompt_builder.datetime")
def test_summary_prompt_builder_timezone_handling(mock_datetime):
    # Arrange
    builder = SummaryPromptBuilder()

    # We want datetime.now(tz=tz) to return our specific time
    # 2025-01-01 14:00:00 UTC
    # In Australia/Sydney this is 2025-01-02 01:00:00 AEDT
    mock_now_utc = datetime(2025, 1, 1, 14, 0, 0, tzinfo=UTC)

    def side_effect(tz=None):
        if tz:
            return mock_now_utc.astimezone(tz)
        return mock_now_utc

    mock_datetime.now.side_effect = side_effect

    summary_input = SummaryInput(
        contact_id=1,
        timezone="Australia/Sydney",
        contact_name="John Doe",
        company=None,
        job_title=None,
        recent_notes=[],
        recent_journals=[],
        future_journals=[],
        relationships=[],
        recent_history=[],
        important_dates=[],
        previous_summary=None,
        activity_stats=[],
    )

    # Act
    prompt = builder.build(summary_input)

    # Assert
    assert "Current System Time: 2025-01-02 01:00:00 Australia/Sydney" in prompt


@patch("app.core.contacts.services.summary_prompt_builder.datetime")
def test_summary_prompt_builder_fallback_utc(mock_datetime):
    # Arrange
    builder = SummaryPromptBuilder()

    mock_now_utc = datetime(2025, 1, 1, 14, 0, 0, tzinfo=UTC)

    def side_effect(tz=None):
        if tz:
            return mock_now_utc.astimezone(tz)
        return mock_now_utc

    mock_datetime.now.side_effect = side_effect

    summary_input = SummaryInput(
        contact_id=1,
        timezone="Invalid/Zone",
        contact_name="John Doe",
        company=None,
        job_title=None,
        recent_notes=[],
        recent_journals=[],
        future_journals=[],
        relationships=[],
        recent_history=[],
        important_dates=[],
        previous_summary=None,
        activity_stats=[],
    )

    # Act
    prompt = builder.build(summary_input)

    # Assert
    assert "Current System Time: 2025-01-01 14:00:00 UTC" in prompt
