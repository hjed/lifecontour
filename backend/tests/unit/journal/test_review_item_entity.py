"""Unit tests for ReviewItem domain entity."""

from datetime import UTC, datetime

import pytest
from core_shared.models.journals.review_item import ReviewItem, ReviewReason


@pytest.mark.unit
class TestReviewReason:
    """Test ReviewReason enum."""

    def test_enum_values(self):
        """Test that all expected enum values exist."""
        assert ReviewReason.EXTERNAL_LINK_MATCH.value == "external_link_match"
        assert ReviewReason.DUPLICATE_JOURNAL.value == "duplicate_journal"
        assert ReviewReason.NEEDS_REVIEW.value == "needs_review"

    def test_enum_count(self):
        """Test that the enum has exactly the expected number of members."""
        assert len(ReviewReason) == 3


@pytest.mark.unit
class TestReviewItem:
    """Test ReviewItem entity."""

    def test_create_valid_review_item(self):
        """Test creating a review item with all required fields."""

        item = ReviewItem(
            user_id="test-user-123",
            source_journal_id=10,
            candidate_journal_id=20,
            reason=ReviewReason.DUPLICATE_JOURNAL,
            confidence_score=0.85,
            details={"title_similarity": 0.9, "date_match": True},
        )

        assert item.user_id == "test-user-123"
        assert item.source_journal_id == 10
        assert item.candidate_journal_id == 20
        assert item.reason == ReviewReason.DUPLICATE_JOURNAL
        assert item.confidence_score == 0.85
        assert item.details == {"title_similarity": 0.9, "date_match": True}
        assert item.id is None
        assert item.status == "pending"
        assert item.created_at is None
        assert item.updated_at is None

    def test_create_review_item_with_all_fields(self):
        """Test creating a review item with all fields including optional ones."""
        now = datetime.now(UTC)

        item = ReviewItem(
            id=1,
            user_id="test-user-123",
            source_journal_id=10,
            candidate_journal_id=20,
            reason=ReviewReason.NEEDS_REVIEW,
            confidence_score=0.65,
            details=None,
            status="resolved",
            created_at=now,
            updated_at=now,
        )

        assert item.id == 1
        assert item.status == "resolved"
        assert item.created_at == now
        assert item.updated_at == now

    def test_default_status_is_pending(self):
        """Test that default status is 'pending'."""
        item = ReviewItem(
            user_id="test-user-123",
            source_journal_id=10,
            candidate_journal_id=20,
            reason=ReviewReason.EXTERNAL_LINK_MATCH,
            confidence_score=0.95,
            details=None,
        )

        assert item.status == "pending"

    def test_details_can_be_none(self):
        """Test that details can be None."""
        item = ReviewItem(
            user_id="test-user-123",
            source_journal_id=10,
            candidate_journal_id=20,
            reason=ReviewReason.NEEDS_REVIEW,
            confidence_score=0.7,
            details=None,
        )

        assert item.details is None

    def test_confidence_score_zero_is_valid(self):
        """Test that confidence score of 0.0 is valid."""
        item = ReviewItem(
            user_id="test-user-123",
            source_journal_id=10,
            candidate_journal_id=20,
            reason=ReviewReason.NEEDS_REVIEW,
            confidence_score=0.0,
            details=None,
        )

        assert item.confidence_score == 0.0

    def test_confidence_score_one_is_valid(self):
        """Test that confidence score of 1.0 is valid."""
        item = ReviewItem(
            user_id="test-user-123",
            source_journal_id=10,
            candidate_journal_id=20,
            reason=ReviewReason.EXTERNAL_LINK_MATCH,
            confidence_score=1.0,
            details=None,
        )

        assert item.confidence_score == 1.0

    def test_confidence_score_above_one_raises_error(self):
        """Test that confidence score above 1.0 raises validation error."""
        from core_shared.models.journals import JournalValidationError

        with pytest.raises(JournalValidationError, match="confidence_score"):
            ReviewItem(
                user_id="test-user-123",
                source_journal_id=10,
                candidate_journal_id=20,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=1.1,
                details=None,
            )

    def test_confidence_score_below_zero_raises_error(self):
        """Test that confidence score below 0.0 raises validation error."""
        from core_shared.models.journals import JournalValidationError

        with pytest.raises(JournalValidationError, match="confidence_score"):
            ReviewItem(
                user_id="test-user-123",
                source_journal_id=10,
                candidate_journal_id=20,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=-0.1,
                details=None,
            )

    def test_same_source_and_candidate_journal_raises_error(self):
        """Test that source and candidate journal IDs cannot be the same."""
        from core_shared.models.journals import JournalValidationError

        with pytest.raises(
            JournalValidationError, match="source_journal_id.*candidate_journal_id"
        ):
            ReviewItem(
                user_id="test-user-123",
                source_journal_id=10,
                candidate_journal_id=10,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=0.8,
                details=None,
            )

    def test_empty_user_id_raises_error(self):
        """Test that empty user_id raises validation error."""
        from core_shared.models.journals import JournalValidationError

        with pytest.raises(JournalValidationError, match="user_id"):
            ReviewItem(
                user_id="",
                source_journal_id=10,
                candidate_journal_id=20,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=0.8,
                details=None,
            )

    def test_whitespace_user_id_raises_error(self):
        """Test that whitespace-only user_id raises validation error."""
        from core_shared.models.journals import JournalValidationError

        with pytest.raises(JournalValidationError, match="user_id"):
            ReviewItem(
                user_id="   ",
                source_journal_id=10,
                candidate_journal_id=20,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=0.8,
                details=None,
            )

    def test_all_review_reasons_are_valid(self):
        """Test creating review items with each reason type."""
        for reason in ReviewReason:
            item = ReviewItem(
                user_id="test-user-123",
                source_journal_id=10,
                candidate_journal_id=20,
                reason=reason,
                confidence_score=0.7,
                details=None,
            )
            assert item.reason == reason
