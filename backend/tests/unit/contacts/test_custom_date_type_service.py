"""Unit tests for CustomDateTypeService."""

from unittest.mock import AsyncMock

import pytest

from app.core.contacts.services.custom_date_type_service import CustomDateTypeService


@pytest.fixture
def mock_repo():
    """Create a mock custom date type repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def service(mock_repo):
    """Create a CustomDateTypeService instance."""
    return CustomDateTypeService(mock_repo)


class TestCreate:
    """Test the create unit of work."""

    @pytest.mark.asyncio
    async def test_create_persists_and_returns(
        self, service, mock_repo, mock_transaction
    ):
        """create delegates to the repo and returns the created entity."""
        created = object()
        mock_repo.create.return_value = created

        result = await service.create("Anniversary", transaction=mock_transaction)

        assert result is created
        mock_repo.create.assert_awaited_once_with("Anniversary")


class TestDelete:
    """Test the delete unit of work."""

    @pytest.mark.asyncio
    async def test_delete_delegates_to_repo(self, service, mock_repo, mock_transaction):
        """delete delegates to the repo with the given id."""
        await service.delete(7, transaction=mock_transaction)

        mock_repo.delete.assert_awaited_once_with(7)
