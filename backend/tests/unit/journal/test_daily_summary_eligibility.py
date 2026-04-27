"""Unit tests for DailySummaryEligibilityChecker."""

from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)


class TestDailySummaryEligibilityChecker:
    """Test eligibility logic for daily summary generation."""

    def test_eligible_with_two_journals(self) -> None:
        """Two journals meets the default threshold."""
        checker = DailySummaryEligibilityChecker()
        assert checker.is_eligible(journal_count=2) is True

    def test_eligible_with_many_journals(self) -> None:
        """Many journals is clearly eligible."""
        checker = DailySummaryEligibilityChecker()
        assert checker.is_eligible(journal_count=10) is True

    def test_ineligible_with_zero_journals(self) -> None:
        """Zero journals is ineligible."""
        checker = DailySummaryEligibilityChecker()
        assert checker.is_eligible(journal_count=0) is False

    def test_ineligible_with_one_journal(self) -> None:
        """Single journal is ineligible — needs multiple."""
        checker = DailySummaryEligibilityChecker()
        assert checker.is_eligible(journal_count=1) is False

    def test_custom_threshold(self) -> None:
        """Custom threshold can be set."""
        checker = DailySummaryEligibilityChecker(min_journals=3)
        assert checker.is_eligible(journal_count=2) is False
        assert checker.is_eligible(journal_count=3) is True
        assert checker.is_eligible(journal_count=4) is True

    def test_threshold_of_one(self) -> None:
        """Threshold of 1 means any journals qualify."""
        checker = DailySummaryEligibilityChecker(min_journals=1)
        assert checker.is_eligible(journal_count=0) is False
        assert checker.is_eligible(journal_count=1) is True
