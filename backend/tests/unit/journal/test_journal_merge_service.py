"""Unit tests for JournalMergeService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
)

from app.core.journal.services.journal_merge_service import (
    JournalMergeConflictError,
    JournalMergeService,
)


@pytest.fixture
def mock_journal_repo():
    return AsyncMock()


@pytest.fixture
def mock_event_publisher():
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    mock_tx = AsyncMock()
    # Mocking standard execute response for any select queries
    # to return empty rows unless overridden
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.fetchone.return_value = None
    mock_tx.execute.return_value = mock_result
    return mock_tx


@pytest.fixture
def merge_service(mock_journal_repo, mock_event_publisher):
    return JournalMergeService(
        journal_repo=mock_journal_repo,
        event_publisher=mock_event_publisher,
    )


def create_test_journal(
    id: int,
    title: str = "Test",
    content: str = "",
) -> Journal:
    now = datetime(2024, 1, 1)
    return Journal(
        id=id,
        user_id="user123",
        title=title,
        content=content,
        event_date_range=EventDateRange(start=now, end=now),
    )


class TestJournalMergeService:
    @pytest.mark.asyncio
    async def test_merge_journals_basic_fields(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        target = create_test_journal(
            id=1, title="Target Title", content="Target Content"
        )
        source = create_test_journal(
            id=2, title="Target Title", content="Source Content"
        )

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        result = await merge_service.merge_journals(1, 2, mock_transaction)

        assert result.title == "Target Title"
        # Content should be concatenated
        assert result.content == "Target Content\n\n---\n\nSource Content"
        mock_journal_repo.save.assert_called_once()
        mock_journal_repo.delete.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_merge_journals_raises_conflict_on_title(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        target = create_test_journal(id=1, title="Target Title")
        source = create_test_journal(id=2, title="Source Title")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )

        with pytest.raises(JournalMergeConflictError):
            await merge_service.merge_journals(1, 2, mock_transaction)

    @pytest.mark.asyncio
    async def test_merge_relationship_queries_executed(
        self, merge_service, mock_journal_repo, mock_transaction, mock_event_publisher
    ):
        target = create_test_journal(id=1, title="Target Title")
        source = create_test_journal(id=2, title="Target Title")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        await merge_service.merge_journals(1, 2, mock_transaction)

        # Verify that execute was called multiple times for merging relationships
        execute_calls = mock_transaction.execute.call_args_list
        queries = [call[0][0].text for call in execute_calls]

        # We expect queries like UPDATE tags, contacts, duplicate removal, etc.
        assert any("journal_tag_assignments" in q for q in queries)
        assert any("journal_contact_relationships" in q for q in queries)
        assert any("journal_external_event_links" in q for q in queries)
