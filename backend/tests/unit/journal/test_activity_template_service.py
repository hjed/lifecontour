"""Unit tests for ActivityTemplateService."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.journal.services.activity_template_service import ActivityTemplateService


@pytest.fixture
def mock_repo():
    """Create a mock activity template repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def service(mock_repo):
    """Create an ActivityTemplateService instance."""
    return ActivityTemplateService(mock_repo)


class TestCreate:
    """Test the create unit of work."""

    @pytest.mark.asyncio
    async def test_create_persists_and_returns(
        self, service, mock_repo, mock_transaction
    ):
        """create delegates to the repo and returns the saved entity."""
        template = MagicMock()
        saved = MagicMock()
        mock_repo.save.return_value = saved

        result = await service.create(template, transaction=mock_transaction)

        assert result is saved
        mock_repo.save.assert_awaited_once_with(template)


class TestUpdate:
    """Test the update unit of work."""

    @pytest.mark.asyncio
    async def test_update_persists_and_returns(
        self, service, mock_repo, mock_transaction
    ):
        """update delegates to the repo and returns the saved entity."""
        template = MagicMock()
        mock_repo.save.return_value = template

        result = await service.update(template, transaction=mock_transaction)

        assert result is template
        mock_repo.save.assert_awaited_once_with(template)


class TestDelete:
    """Test the delete unit of work."""

    @pytest.mark.asyncio
    async def test_delete_delegates_to_repo(self, service, mock_repo, mock_transaction):
        """delete delegates to the repo with the given id."""
        template_id = str(uuid4())

        await service.delete(template_id, transaction=mock_transaction)

        mock_repo.delete.assert_awaited_once_with(template_id)
