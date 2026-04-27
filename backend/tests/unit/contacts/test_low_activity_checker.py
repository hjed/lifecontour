"""Unit tests for LowActivityChecker — heuristic for auto-disabling summaries."""

import pytest
from core_shared.models.contacts.entities import ContactSummary, SummaryStatus

from app.core.contacts.services.summary_generation_service import (
    LowActivityChecker,
    SummaryInput,
)


def _make_input(
    num_notes: int = 0,
    num_journals: int = 0,
    num_history: int = 0,
) -> SummaryInput:
    """Create a SummaryInput with the specified activity counts."""
    return SummaryInput(
        contact_id=1,
        contact_name="John Doe",
        company="Acme",
        job_title="Engineer",
        recent_notes=[f"Note {i}" for i in range(num_notes)],
        recent_journals=[
            {"title": f"Journal {i}", "content": f"Content {i}"}
            for i in range(num_journals)
        ],
        future_journals=[],
        relationships=[],
        recent_history=[f"Changed field_{i}" for i in range(num_history)],
        important_dates=[],
        previous_summary=None,
        activity_stats=[],
    )


@pytest.mark.unit
class TestLowActivityChecker:
    """Tests for LowActivityChecker heuristic."""

    def test_below_threshold_returns_true(self):
        """Test that a contact with very little activity is flagged as low."""
        checker = LowActivityChecker()
        summary_input = _make_input(num_notes=0, num_journals=0, num_history=1)

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=None
        )
        assert result is True

    def test_at_threshold_returns_false(self):
        """Test that a contact at the threshold is NOT flagged as low."""
        checker = LowActivityChecker()
        summary_input = _make_input(num_notes=1, num_journals=1, num_history=0)

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=None
        )
        assert result is False

    def test_above_threshold_returns_false(self):
        """Test that a contact with good activity is NOT flagged as low."""
        checker = LowActivityChecker()
        summary_input = _make_input(num_notes=3, num_journals=5, num_history=2)

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=None
        )
        assert result is False

    def test_user_override_never_auto_disables(self):
        """Test that user override prevents auto-disable regardless of activity."""
        checker = LowActivityChecker()
        summary_input = _make_input(num_notes=0, num_journals=0, num_history=0)
        existing = ContactSummary(
            contact_id=1,
            is_user_override=True,
            status=SummaryStatus.GENERATED,
        )

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=existing
        )
        assert result is False

    def test_user_re_enabled_never_auto_disables(self):
        """Test that a contact manually re-enabled by user is not auto-disabled.

        When a user explicitly sets is_disabled=False after an auto-disable,
        the is_user_override flag is set to True, preventing future auto-disable.
        """
        checker = LowActivityChecker()
        summary_input = _make_input(num_notes=0, num_journals=0, num_history=0)
        existing = ContactSummary(
            contact_id=1,
            is_user_override=True,
            is_disabled=False,
            status=SummaryStatus.PENDING,
        )

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=existing
        )
        assert result is False

    def test_custom_threshold(self):
        """Test that a custom threshold value is respected."""
        checker = LowActivityChecker(min_activity_threshold=5)
        # 3 total interactions: below custom threshold of 5
        summary_input = _make_input(num_notes=1, num_journals=1, num_history=1)

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=None
        )
        assert result is True

    def test_no_existing_summary_allows_auto_disable(self):
        """Test that contacts with no existing summary can be auto-disabled."""
        checker = LowActivityChecker()
        summary_input = _make_input(num_notes=0, num_journals=0, num_history=0)

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=None
        )
        assert result is True

    def test_zero_activity_is_low(self):
        """Test zero total activity counts as low activity."""
        checker = LowActivityChecker()
        summary_input = _make_input()

        result = checker.should_auto_disable(
            summary_input=summary_input, existing_summary=None
        )
        assert result is True
