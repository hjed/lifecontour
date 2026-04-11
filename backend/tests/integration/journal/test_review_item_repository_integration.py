"""Integration tests for SqlReviewItemRepository."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    ReviewItem,
    ReviewReason,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.review_item_repository import (
    SqlReviewItemRepository,
)

USER_ID = "test-user-123"


@pytest_asyncio.fixture
async def review_item_repository(
    async_connection: AsyncConnection,
) -> SqlReviewItemRepository:
    """Create a review item repository for testing."""
    return SqlReviewItemRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


async def _create_journal(
    journal_repository: SqlJournalRepository,
    *,
    title: str = "Test Journal",
    content: str = "Test content",
    hours_offset: int = 0,
) -> Journal:
    """Helper to create a test journal."""
    now = datetime.now(UTC) + timedelta(hours=hours_offset)
    journal = Journal(
        user_id=USER_ID,
        title=title,
        content=content,
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=1),
        ),
    )
    return await journal_repository.save(journal)


async def _setup_review_item(
    journal_repository: SqlJournalRepository,
    review_item_repository: SqlReviewItemRepository,
) -> ReviewItem:
    """Helper to setup a basic review item for test setups."""
    source = await _create_journal(journal_repository, title="Source")
    candidate = await _create_journal(
        journal_repository, title="Candidate", hours_offset=1
    )

    created, _ = await review_item_repository.create(
        _make_review_item(
            source_journal_id=source.id,  # type: ignore[arg-type]
            candidate_journal_id=candidate.id,  # type: ignore[arg-type]
        )
    )

    assert created.id is not None
    return created


def _make_review_item(
    *,
    source_journal_id: int,
    candidate_journal_id: int,
    reason: ReviewReason = ReviewReason.DUPLICATE_JOURNAL,
    confidence_score: float = 0.85,
    details: dict[str, Any] | None = None,
) -> ReviewItem:
    """Helper to create a ReviewItem entity."""
    return ReviewItem(
        user_id=USER_ID,
        source_journal_id=source_journal_id,
        candidate_journal_id=candidate_journal_id,
        reason=reason,
        confidence_score=confidence_score,
        details=details or {"matched_field": "title"},
    )


@pytest.mark.integration
class TestReviewItemRepositoryCreate:
    """Test review item creation operations."""

    async def test_create_returns_item_with_id_and_timestamps(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Creating a review item should return it with id and timestamps set."""
        source = await _create_journal(journal_repository, title="Source Journal")
        candidate = await _create_journal(
            journal_repository, title="Candidate Journal", hours_offset=1
        )

        review_item = _make_review_item(
            source_journal_id=source.id,  # type: ignore[arg-type]
            candidate_journal_id=candidate.id,  # type: ignore[arg-type]
        )

        created, is_new = await review_item_repository.create(review_item)

        assert is_new is True
        assert created.id is not None
        assert created.created_at is not None
        assert created.updated_at is not None
        assert created.user_id == USER_ID
        assert created.source_journal_id == source.id
        assert created.candidate_journal_id == candidate.id
        assert created.reason == ReviewReason.DUPLICATE_JOURNAL
        assert created.confidence_score == pytest.approx(0.85)
        assert created.status == "pending"

    async def test_create_preserves_details_json(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Details dict should be round-tripped through JSON correctly."""
        source = await _create_journal(journal_repository, title="Source")
        candidate = await _create_journal(
            journal_repository, title="Candidate", hours_offset=1
        )

        details = {
            "title_similarity": 0.92,
            "matched_fields": ["title", "content"],
        }
        review_item = _make_review_item(
            source_journal_id=source.id,  # type: ignore[arg-type]
            candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            details=details,
        )

        created, _ = await review_item_repository.create(review_item)

        assert created.details == details

    async def test_create_idempotent_on_duplicate(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Second create with same source+candidate pair returns the existing item."""
        source = await _create_journal(journal_repository, title="Source")
        candidate = await _create_journal(
            journal_repository, title="Candidate", hours_offset=1
        )

        first = _make_review_item(
            source_journal_id=source.id,  # type: ignore[arg-type]
            candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            confidence_score=0.8,
        )
        created_first, is_new_first = await review_item_repository.create(first)

        second = _make_review_item(
            source_journal_id=source.id,  # type: ignore[arg-type]
            candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            confidence_score=0.95,  # Different score
        )
        created_second, is_new_second = await review_item_repository.create(second)

        # Should return the existing item (same ID, original score)
        assert is_new_first is True
        assert is_new_second is False
        assert created_second.id == created_first.id
        assert created_second.confidence_score == pytest.approx(
            0.8
        )  # Original, not 0.95

    async def test_create_with_different_reasons(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Each ReviewReason value should persist correctly."""
        source = await _create_journal(journal_repository, title="Source")
        candidate = await _create_journal(
            journal_repository, title="Candidate", hours_offset=1
        )

        review_item = _make_review_item(
            source_journal_id=source.id,  # type: ignore[arg-type]
            candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            reason=ReviewReason.EXTERNAL_LINK_MATCH,
        )

        created, _ = await review_item_repository.create(review_item)

        assert created.reason == ReviewReason.EXTERNAL_LINK_MATCH

    async def test_create_with_null_details(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Null details should be handled correctly."""
        source = await _create_journal(journal_repository, title="Source")
        candidate = await _create_journal(
            journal_repository, title="Candidate", hours_offset=1
        )

        review_item = ReviewItem(
            user_id=USER_ID,
            source_journal_id=source.id,  # type: ignore[arg-type]
            candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            reason=ReviewReason.NEEDS_REVIEW,
            confidence_score=0.5,
            details=None,
        )

        created, _ = await review_item_repository.create(review_item)

        assert created.details is None


@pytest.mark.integration
class TestReviewItemRepositoryFindPending:
    """Test find_pending_by_journal_id operations."""

    async def test_find_pending_returns_matching_items(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should return all pending review items for a source journal."""
        source = await _create_journal(journal_repository, title="Source")
        candidate1 = await _create_journal(
            journal_repository, title="Candidate 1", hours_offset=1
        )
        candidate2 = await _create_journal(
            journal_repository, title="Candidate 2", hours_offset=2
        )

        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=candidate1.id,  # type: ignore[arg-type]
                confidence_score=0.9,
            )
        )
        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=candidate2.id,  # type: ignore[arg-type]
                confidence_score=0.7,
            )
        )

        assert source.id is not None
        pending = await review_item_repository.find_pending_by_journal_id(
            source.id, USER_ID
        )

        assert len(pending) == 2

    async def test_find_pending_ordered_by_confidence_desc(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Results should be ordered by confidence_score descending."""
        source = await _create_journal(journal_repository, title="Source")
        low_conf = await _create_journal(
            journal_repository, title="Low Confidence", hours_offset=1
        )
        high_conf = await _create_journal(
            journal_repository, title="High Confidence", hours_offset=2
        )

        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=low_conf.id,  # type: ignore[arg-type]
                confidence_score=0.5,
            )
        )
        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=high_conf.id,  # type: ignore[arg-type]
                confidence_score=0.95,
            )
        )

        assert source.id is not None
        pending = await review_item_repository.find_pending_by_journal_id(
            source.id, USER_ID
        )

        assert len(pending) == 2
        assert pending[0].confidence_score == pytest.approx(0.95)
        assert pending[1].confidence_score == pytest.approx(0.5)

    async def test_find_pending_returns_empty_for_no_matches(
        self,
        review_item_repository: SqlReviewItemRepository,
    ):
        """Should return empty list when no pending review items exist."""
        pending = await review_item_repository.find_pending_by_journal_id(
            99999, USER_ID
        )

        assert pending == []

    async def test_find_pending_excludes_other_source_journals(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should only return items for the specified source journal."""
        source1 = await _create_journal(journal_repository, title="Source 1")
        source2 = await _create_journal(
            journal_repository, title="Source 2", hours_offset=1
        )
        candidate = await _create_journal(
            journal_repository, title="Candidate", hours_offset=2
        )

        # Create review item for source1 only
        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source1.id,  # type: ignore[arg-type]
                candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            )
        )

        # Query for source2 should return nothing
        assert source2.id is not None
        pending = await review_item_repository.find_pending_by_journal_id(
            source2.id, USER_ID
        )

        assert pending == []


OTHER_USER_ID = "other-user-456"


@pytest.mark.integration
class TestReviewItemRepositoryFindPendingByUser:
    """Test find_pending_by_user operations."""

    async def test_returns_all_pending_items_for_user(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should return all pending review items for a user."""
        source = await _create_journal(journal_repository, title="Source")
        candidate1 = await _create_journal(
            journal_repository, title="Candidate 1", hours_offset=1
        )
        candidate2 = await _create_journal(
            journal_repository, title="Candidate 2", hours_offset=2
        )

        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=candidate1.id,  # type: ignore[arg-type]
            )
        )
        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=candidate2.id,  # type: ignore[arg-type]
            )
        )

        items = await review_item_repository.find_pending_by_user(USER_ID)

        assert len(items) == 2

    async def test_respects_limit_and_offset(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should paginate results using limit and offset."""
        source = await _create_journal(journal_repository, title="Source")
        candidates = []
        for i in range(3):
            c = await _create_journal(
                journal_repository, title=f"Candidate {i}", hours_offset=i + 1
            )
            candidates.append(c)
            await review_item_repository.create(
                _make_review_item(
                    source_journal_id=source.id,  # type: ignore[arg-type]
                    candidate_journal_id=c.id,  # type: ignore[arg-type]
                    confidence_score=0.9 - i * 0.1,
                )
            )

        page1 = await review_item_repository.find_pending_by_user(
            USER_ID, limit=2, offset=0
        )
        page2 = await review_item_repository.find_pending_by_user(
            USER_ID, limit=2, offset=2
        )

        assert len(page1) == 2
        assert len(page2) == 1

    async def test_returns_empty_for_no_pending(
        self,
        review_item_repository: SqlReviewItemRepository,
    ):
        """Should return empty list when no pending items exist."""
        items = await review_item_repository.find_pending_by_user(USER_ID)
        assert items == []

    async def test_ordered_by_confidence_desc(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Results should be ordered by confidence_score descending."""
        source = await _create_journal(journal_repository, title="Source")
        low = await _create_journal(journal_repository, title="Low", hours_offset=1)
        high = await _create_journal(journal_repository, title="High", hours_offset=2)

        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=low.id,  # type: ignore[arg-type]
                confidence_score=0.3,
            )
        )
        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=high.id,  # type: ignore[arg-type]
                confidence_score=0.95,
            )
        )

        items = await review_item_repository.find_pending_by_user(USER_ID)

        assert items[0].confidence_score == pytest.approx(0.95)
        assert items[1].confidence_score == pytest.approx(0.3)


@pytest.mark.integration
class TestReviewItemRepositoryCountPendingByUser:
    """Test count_pending_by_user operations."""

    async def test_returns_correct_count(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should return correct count of pending items for user."""
        source = await _create_journal(journal_repository, title="Source")
        c1 = await _create_journal(journal_repository, title="C1", hours_offset=1)
        c2 = await _create_journal(journal_repository, title="C2", hours_offset=2)

        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=c1.id,  # type: ignore[arg-type]
            )
        )
        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source.id,  # type: ignore[arg-type]
                candidate_journal_id=c2.id,  # type: ignore[arg-type]
            )
        )

        count = await review_item_repository.count_pending_by_user(USER_ID)
        assert count == 2

    async def test_returns_zero_when_none(
        self,
        review_item_repository: SqlReviewItemRepository,
    ):
        """Should return zero when no pending items exist."""
        count = await review_item_repository.count_pending_by_user(USER_ID)
        assert count == 0


@pytest.mark.integration
class TestReviewItemRepositoryFindPendingJournalIds:
    """Test find_pending_journal_ids_by_user operations."""

    async def test_returns_journal_ids_with_pending_reviews(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should return distinct journal IDs that have pending review items."""
        source1 = await _create_journal(journal_repository, title="Source 1")
        source2 = await _create_journal(
            journal_repository, title="Source 2", hours_offset=1
        )
        candidate = await _create_journal(
            journal_repository, title="Candidate", hours_offset=2
        )
        # Journal with no review items
        await _create_journal(journal_repository, title="Clean Journal", hours_offset=3)

        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source1.id,  # type: ignore[arg-type]
                candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            )
        )
        await review_item_repository.create(
            _make_review_item(
                source_journal_id=source2.id,  # type: ignore[arg-type]
                candidate_journal_id=candidate.id,  # type: ignore[arg-type]
            )
        )

        journal_ids = await review_item_repository.find_pending_journal_ids_by_user(
            USER_ID
        )

        # Should include source journals and candidate journal
        assert source1.id in journal_ids
        assert source2.id in journal_ids
        assert candidate.id in journal_ids

    async def test_returns_empty_when_no_pending(
        self,
        review_item_repository: SqlReviewItemRepository,
    ):
        """Should return empty set when no pending review items exist."""
        journal_ids = await review_item_repository.find_pending_journal_ids_by_user(
            USER_ID
        )
        assert journal_ids == set()


@pytest.mark.integration
class TestReviewItemRepositoryUpdateStatus:
    """Test update_status operations."""

    async def test_updates_status_to_resolved(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should update a pending review item to resolved."""
        created = await _setup_review_item(journal_repository, review_item_repository)
        assert created.id is not None
        updated = await review_item_repository.update_status(
            created.id, "resolved", USER_ID
        )

        assert updated is not None
        assert updated.status == "resolved"
        assert updated.id == created.id

    async def test_updates_status_to_dismissed(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Should update a pending review item to dismissed."""
        created = await _setup_review_item(journal_repository, review_item_repository)
        assert created.id is not None
        updated = await review_item_repository.update_status(
            created.id, "dismissed", USER_ID
        )

        assert updated is not None
        assert updated.status == "dismissed"

    async def test_returns_none_for_nonexistent(
        self,
        review_item_repository: SqlReviewItemRepository,
    ):
        """Should return None when review item doesn't exist."""
        result = await review_item_repository.update_status(99999, "resolved", USER_ID)
        assert result is None

    async def test_resolved_item_excluded_from_pending(
        self,
        review_item_repository: SqlReviewItemRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Resolved items should not appear in pending queries."""
        created = await _setup_review_item(journal_repository, review_item_repository)
        assert created.id is not None
        await review_item_repository.update_status(created.id, "resolved", USER_ID)

        pending = await review_item_repository.find_pending_by_user(USER_ID)
        assert len(pending) == 0

        count = await review_item_repository.count_pending_by_user(USER_ID)
        assert count == 0
