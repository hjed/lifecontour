"""Unit tests for ReviewItemService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.journals.review_item import ReviewItem, ReviewReason

from app.core.journal.services.review_item_service import ReviewItemService


@pytest.fixture
def mock_review_item_repo():
    return AsyncMock()


@pytest.fixture
def mock_journal_service():
    return AsyncMock()


@pytest.fixture
def mock_merge_service():
    # has_base_conflicts is sync; merge_journals is async.
    service = AsyncMock()
    service.has_base_conflicts = MagicMock(return_value=False)
    return service


@pytest.fixture
def mock_transaction():
    return AsyncMock()


@pytest.fixture
def review_item_service(
    mock_review_item_repo, mock_journal_service, mock_merge_service
):
    return ReviewItemService(
        review_item_repo=mock_review_item_repo,
        journal_service=mock_journal_service,
        journal_merge_service=mock_merge_service,
    )


def _journal(journal_id: int, user_id: str = "user-1") -> Journal:
    return Journal(
        id=journal_id,
        user_id=user_id,
        title=f"Journal {journal_id}",
        content="",
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        ),
    )


def _review_item(item_id: int, source: int, candidate: int) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        user_id="user-1",
        source_journal_id=source,
        candidate_journal_id=candidate,
        reason=ReviewReason.NEEDS_REVIEW,
        confidence_score=0.9,
        details=None,
    )


class TestCreateReviewItem:
    @pytest.mark.asyncio
    async def test_create_review_item_delegates_to_repo(
        self, review_item_service, mock_review_item_repo, mock_transaction
    ):
        item = _review_item(1, 10, 20)
        mock_review_item_repo.create.return_value = (item, True)

        created, is_new = await review_item_service.create_review_item(
            item, transaction=mock_transaction
        )

        assert created is item
        assert is_new is True
        mock_review_item_repo.create.assert_awaited_once_with(item)


class TestAutoMergeReviewItems:
    @pytest.mark.asyncio
    async def test_merges_items_without_conflicts(
        self,
        review_item_service,
        mock_review_item_repo,
        mock_journal_service,
        mock_merge_service,
        mock_transaction,
    ):
        """Each conflict-free pair is merged and counted."""
        item = _review_item(1, 10, 20)
        mock_review_item_repo.find_pending_by_user.return_value = [item]
        mock_review_item_repo.count_pending_by_user.return_value = 0
        mock_journal_service.get_journal.side_effect = [
            _journal(10),
            _journal(20),
        ]

        (
            merged,
            skipped,
            remaining,
            errors,
        ) = await review_item_service.auto_merge_review_items(
            "user-1", transaction=mock_transaction
        )

        assert merged == 1
        assert skipped == 0
        assert remaining == 0
        assert errors == []
        mock_merge_service.merge_journals.assert_awaited_once_with(
            target_id=20, source_id=10, transaction=mock_transaction
        )

    @pytest.mark.asyncio
    async def test_skips_conflicting_items(
        self,
        review_item_service,
        mock_review_item_repo,
        mock_journal_service,
        mock_merge_service,
        mock_transaction,
    ):
        """Items with base conflicts are skipped, not merged."""
        item = _review_item(1, 10, 20)
        mock_review_item_repo.find_pending_by_user.return_value = [item]
        mock_review_item_repo.count_pending_by_user.return_value = 1
        mock_journal_service.get_journal.side_effect = [
            _journal(10),
            _journal(20),
        ]
        mock_merge_service.has_base_conflicts.return_value = True

        (
            merged,
            skipped,
            remaining,
            errors,
        ) = await review_item_service.auto_merge_review_items(
            "user-1", transaction=mock_transaction
        )

        assert merged == 0
        assert skipped == 1
        mock_merge_service.merge_journals.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_merge_is_recorded_and_loop_continues(
        self,
        review_item_service,
        mock_review_item_repo,
        mock_journal_service,
        mock_merge_service,
        mock_transaction,
    ):
        """A failing merge is recorded as an error; other items still process.

        The mock transaction's ``begin_nested`` (used by the savepoint helper) is
        configured as an async context manager so the savepoint wrapping works.
        """
        item_ok = _review_item(1, 10, 20)
        item_bad = _review_item(2, 30, 40)
        mock_review_item_repo.find_pending_by_user.return_value = [item_bad, item_ok]
        mock_review_item_repo.count_pending_by_user.return_value = 0
        mock_journal_service.get_journal.side_effect = [
            _journal(30),
            _journal(40),
            _journal(10),
            _journal(20),
        ]

        # First merge raises, second succeeds.
        mock_merge_service.merge_journals.side_effect = [
            RuntimeError("boom"),
            None,
        ]

        # Provide an async-context-manager begin_nested for savepoint().
        nested = AsyncMock()
        mock_transaction.begin_nested.return_value = nested

        (
            merged,
            skipped,
            remaining,
            errors,
        ) = await review_item_service.auto_merge_review_items(
            "user-1", transaction=mock_transaction
        )

        assert merged == 1
        assert len(errors) == 1
        assert "30" in errors[0]

    @pytest.mark.asyncio
    async def test_dismisses_review_item_when_journal_missing(
        self,
        review_item_service,
        mock_review_item_repo,
        mock_journal_service,
        mock_transaction,
    ):
        """A deleted journal causes the review item to be resolved and skipped."""
        item = _review_item(1, 10, 20)
        mock_review_item_repo.find_pending_by_user.return_value = [item]
        mock_review_item_repo.count_pending_by_user.return_value = 0
        mock_journal_service.get_journal.side_effect = [None, _journal(20)]

        (
            merged,
            skipped,
            remaining,
            errors,
        ) = await review_item_service.auto_merge_review_items(
            "user-1", transaction=mock_transaction
        )

        assert merged == 0
        assert skipped == 1
        mock_review_item_repo.update_status.assert_awaited_once_with(
            1, new_status="resolved", user_id="user-1"
        )
