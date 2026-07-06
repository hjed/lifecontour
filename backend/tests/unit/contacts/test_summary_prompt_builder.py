"""Unit tests for SummaryPromptBuilder — prompt construction for AI summaries."""

from typing import Any

import pytest

from app.core.contacts.services.summary_generation_service import (
    ActivityStatsBucket,
    SummaryInput,
)
from app.core.contacts.services.summary_prompt_builder import SummaryPromptBuilder


def _make_input(**overrides: Any) -> SummaryInput:
    """Create a SummaryInput with sensible defaults and optional overrides."""
    defaults: dict[str, Any] = {
        "contact_id": 1,
        "contact_name": "John Doe",
        "company": "Acme Corp",
        "job_title": "Software Engineer",
        "recent_notes": ["Had coffee on Tuesday", "Needs help with project X"],
        "recent_journals": [
            {
                "title": "Lunch with John",
                "content": "Discussed roadmap",
                "date": "2026-04-01",
            },
            {
                "title": "Team meeting",
                "content": "John presented demo",
                "date": "2026-03-15",
            },
        ],
        "future_journals": [],
        "relationships": ["Friend: Jane Smith", "Colleague: Bob Wilson"],
        "recent_history": [
            "Changed company from OldCo to Acme Corp",
            "Added note: Follow up needed",
        ],
        "important_dates": ["Birthday: March 15"],
        "previous_summary": None,
        "activity_stats": [],
    }
    defaults.update(overrides)
    return SummaryInput(**defaults)


@pytest.mark.unit
class TestSummaryPromptBuilder:
    """Tests for SummaryPromptBuilder."""

    def test_prompt_contains_contact_name(self):
        """Test prompt includes the contact's name."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "John Doe" in prompt

    def test_prompt_contains_company_and_role(self):
        """Test prompt includes company and job title context."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "Acme Corp" in prompt
        assert "Software Engineer" in prompt

    def test_prompt_includes_recent_notes(self):
        """Test prompt includes recent note content."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "Had coffee on Tuesday" in prompt
        assert "Needs help with project X" in prompt

    def test_prompt_includes_recent_journals(self):
        """Test prompt includes linked journal information."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "## Recent Linked Journals" in prompt
        assert "Lunch with John" in prompt
        assert "Team meeting" in prompt

    def test_prompt_includes_future_journals(self):
        """Test prompt includes future scheduled journals under correct section."""
        builder = SummaryPromptBuilder()
        input_data = _make_input(
            future_journals=[
                {
                    "title": "Future Planning",
                    "content": "Discuss Q4",
                    "date": "2026-10-01",
                }
            ]
        )
        prompt = builder.build(input_data)

        assert "## Upcoming Scheduled Events" in prompt
        assert "Future Planning" in prompt

    def test_prompt_includes_journal_metadata(self):
        """Test prompt includes journal types and relationship metadata."""
        builder = SummaryPromptBuilder()
        input_data = _make_input(
            recent_journals=[
                {
                    "title": "Running session",
                    "content": "5k run",
                    "date": "2026-04-01",
                    "journal_types": ["EVENT", "FITNESS"],
                    "relationship_type": "participant",
                    "status": "attending",
                }
            ]
        )
        prompt = builder.build(input_data)

        assert "Running session" in prompt
        assert "types: EVENT, FITNESS" in prompt
        assert "role of contact: participant (attending)" in prompt

    def test_prompt_includes_relationships(self):
        """Test prompt includes relationship context."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "Jane Smith" in prompt
        assert "Bob Wilson" in prompt

    def test_prompt_relationships_disambiguate_from_user(self):
        """Relationships section clarifies contact-to-contact links are not the user's."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "## Relationships" in prompt
        assert "not a relationship" in prompt.lower()
        assert "to the user" in prompt.lower()
        assert "distinct from you, the ai assistant" in prompt.lower()

    def test_prompt_includes_important_dates(self):
        """Test prompt includes important dates."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "Birthday" in prompt or "birthday" in prompt

    def test_prompt_includes_previous_summary(self):
        """Test prompt includes the previous summary for incremental generation."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(
            _make_input(previous_summary="John is a long-time colleague from Acme.")
        )

        assert "John is a long-time colleague from Acme." in prompt

    def test_prompt_without_previous_summary(self):
        """Test prompt works correctly for first-time generation (no prior summary)."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input(previous_summary=None))

        # Should still be a valid prompt
        assert "John Doe" in prompt
        # Should not contain a dedicated "Previous Summary" section
        assert "## Previous Summary" not in prompt

    def test_prompt_includes_activity_stats_preamble(self):
        """Test prompt includes long-term activity statistics."""
        stats = [
            ActivityStatsBucket(period_label="3-12 months ago", event_count=6),
            ActivityStatsBucket(period_label="12-24 months ago", event_count=3),
        ]
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input(activity_stats=stats))

        assert "3-12 months ago" in prompt
        assert "6" in prompt
        assert "12-24 months ago" in prompt

    def test_prompt_omits_stats_when_empty(self):
        """Test prompt doesn't include stats section when no long-term history."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input(activity_stats=[]))

        # There should be no "long-term" or "historical activity" section
        # when there are no stats to show
        assert "historical activity" not in prompt.lower()

    def test_content_truncation_for_long_notes(self):
        """Test that very long note content is truncated."""
        long_note = "A" * 10000
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input(recent_notes=[long_note]))

        # Total prompt should be bounded
        assert len(prompt) < builder.MAX_PROMPT_CHARS

    def test_content_truncation_for_long_journals(self):
        """Test that very long journal content is truncated."""
        long_journal = {
            "title": "A" * 500,
            "content": "B" * 10000,
            "date": "2026-01-01",
        }
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input(recent_journals=[long_journal]))

        assert len(prompt) < builder.MAX_PROMPT_CHARS

    def test_tone_and_safety_instructions_present(self):
        """Test prompt includes conservative tone and safety instructions."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        prompt_lower = prompt.lower()
        # Should instruct conservative/grounded behaviour
        assert "conservative" in prompt_lower or "grounded" in prompt_lower
        assert "evidence" in prompt_lower or "avoid" in prompt_lower

    def test_output_format_instructions(self):
        """Test prompt requests JSON structured output."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "json" in prompt.lower()
        assert "summary_text" in prompt
        assert "follow_up_suggestions" in prompt

    def test_handles_empty_input_gracefully(self):
        """Test prompt generation with minimal/empty input."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(
            _make_input(
                recent_notes=[],
                recent_journals=[],
                relationships=[],
                recent_history=[],
                important_dates=[],
                company=None,
                job_title=None,
            )
        )

        assert "John Doe" in prompt
        # Should still produce a valid prompt
        assert len(prompt) > 0

    def test_prompt_includes_current_system_time(self):
        """Test prompt includes the current system time."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input())

        assert "Current System Time" in prompt
        assert "UTC" in prompt

    def test_prompt_current_time_uses_user_timezone(self):
        """Current system time is rendered in the user's timezone with a label."""
        builder = SummaryPromptBuilder()
        prompt = builder.build(_make_input(), timezone="Australia/Sydney")

        assert "Current System Time" in prompt
        # Explicit timezone label and offset, not a bare UTC timestamp
        assert "AEST" in prompt
        assert "+10:00" in prompt
