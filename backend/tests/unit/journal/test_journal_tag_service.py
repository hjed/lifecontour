"""Unit tests for JournalTagService."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.journals import JournalValidationError
from sqlalchemy.exc import IntegrityError

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.journal_tag_service import (
    JournalTagInUseError,
    JournalTagService,
)


@pytest.fixture
def mock_tag_repo():
    """Create a mock journal tag repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def tag_service(mock_tag_repo):
    """Create a JournalTagService instance."""
    return JournalTagService(mock_tag_repo)


class TestCreateTag:
    """Test the create_tag unit of work."""

    @pytest.mark.asyncio
    async def test_create_tag_persists_and_returns(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """create_tag saves via the repo and returns the saved entity."""
        tag = JournalTag(name="Work", color="#3B82F6")
        saved = JournalTag(id=uuid4(), name="Work", color="#3B82F6")
        mock_tag_repo.save.return_value = saved

        result = await tag_service.create_tag(tag, transaction=mock_transaction)

        assert result is saved
        mock_tag_repo.save.assert_awaited_once_with(tag)

    @pytest.mark.asyncio
    async def test_create_tag_maps_duplicate_name_to_validation_error(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A duplicate-name IntegrityError becomes a JournalValidationError."""
        tag = JournalTag(name="Work", color="#3B82F6")
        mock_tag_repo.save.side_effect = IntegrityError(
            "uq_journal_tags_name", {}, Exception("dup")
        )

        with pytest.raises(JournalValidationError):
            await tag_service.create_tag(tag, transaction=mock_transaction)

    @pytest.mark.asyncio
    async def test_create_tag_reraises_other_integrity_errors(
        self, tag_service, mock_tag_repo, mock_transaction
    ):
        """A non-duplicate IntegrityError is re-raised unchanged."""
        tag = JournalTag(name="Work", color="#3B82F6")
        mock_tag_repo.save.side_effect = IntegrityError(
            "some other constraint", {}, Exception("boom")
        )

        with pytest.raises(IntegrityError):
            await tag_service.create_tag(tag, transaction=mock_transaction)


class TestDeleteTag:
    """Test the delete_tag unit of work."""

    @staticmethod
    def _transaction_with_usage(usage_count: int) -> AsyncMock:
        """Build a mock transaction whose usage query returns ``usage_count``."""
        transaction = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = (usage_count,)
        transaction.execute.return_value = result
        return transaction

    @pytest.mark.asyncio
    async def test_delete_tag_deletes_when_unused(self, tag_service, mock_tag_repo):
        """delete_tag removes the tag when no journals reference it."""
        tag_id = uuid4()
        transaction = self._transaction_with_usage(0)

        await tag_service.delete_tag(tag_id, transaction=transaction)

        mock_tag_repo.delete.assert_awaited_once_with(tag_id)

    @pytest.mark.asyncio
    async def test_delete_tag_rejects_in_use(self, tag_service, mock_tag_repo):
        """delete_tag raises an in-use error when journals reference it."""
        tag_id = uuid4()
        transaction = self._transaction_with_usage(3)
        mock_tag_repo.find_by_id.return_value = JournalTag(
            id=tag_id, name="Busy", color="#000000"
        )

        with pytest.raises(JournalTagInUseError) as exc_info:
            await tag_service.delete_tag(tag_id, transaction=transaction)

        assert exc_info.value.status_code == 409
        mock_tag_repo.delete.assert_not_awaited()


class TestAssignAndRemoveTag:
    """Test the journal<->tag assignment units of work."""

    @pytest.mark.asyncio
    async def test_assign_tag(self, tag_service, mock_tag_repo, mock_transaction):
        """assign_tag delegates to the repo."""
        tag_id = uuid4()
        await tag_service.assign_tag(7, tag_id, transaction=mock_transaction)
        mock_tag_repo.assign_tag.assert_awaited_once_with(7, tag_id)

    @pytest.mark.asyncio
    async def test_remove_tag(self, tag_service, mock_tag_repo, mock_transaction):
        """remove_tag delegates to the repo."""
        tag_id = uuid4()
        await tag_service.remove_tag(7, tag_id, transaction=mock_transaction)
        mock_tag_repo.remove_tag.assert_awaited_once_with(7, tag_id)
