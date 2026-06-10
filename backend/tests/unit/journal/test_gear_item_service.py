"""Unit tests for GearItemService."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.journal.models.events import GearItemUpdated
from app.core.journal.services.gear_item_service import GearItemService


@pytest.fixture
def mock_repo():
    """Create a mock gear item repository."""
    return AsyncMock()


@pytest.fixture
def mock_publisher():
    """Create a mock outbox event publisher."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def service(mock_repo, mock_publisher):
    """Create a GearItemService instance."""
    return GearItemService(gear_item_repo=mock_repo, event_publisher=mock_publisher)


class TestCreate:
    """Test the create unit of work."""

    @pytest.mark.asyncio
    async def test_create_persists_and_returns(
        self, service, mock_repo, mock_transaction
    ):
        """create delegates to the repo and returns the saved entity."""
        gear_item = MagicMock()
        saved = MagicMock()
        mock_repo.save.return_value = saved

        result = await service.create(gear_item, transaction=mock_transaction)

        assert result is saved
        mock_repo.save.assert_awaited_once_with(gear_item)


class TestUpdate:
    """Test the update unit of work."""

    @pytest.mark.asyncio
    async def test_update_publishes_event_when_changed(
        self, service, mock_repo, mock_publisher, mock_transaction
    ):
        """update saves and publishes a GearItemUpdated event when fields changed."""
        gear_item = MagicMock()
        saved = MagicMock()
        saved.id = uuid4()
        mock_repo.save.return_value = saved
        changed_fields: dict[str, Any] = {"name": ("old", "new")}

        result = await service.update(
            gear_item, changed_fields=changed_fields, transaction=mock_transaction
        )

        assert result is saved
        mock_repo.save.assert_awaited_once_with(gear_item)
        mock_publisher.publish.assert_awaited_once()
        event = mock_publisher.publish.await_args.args[0]
        assert isinstance(event, GearItemUpdated)

    @pytest.mark.asyncio
    async def test_update_skips_event_when_no_changes(
        self, service, mock_repo, mock_publisher, mock_transaction
    ):
        """update saves but publishes no event when changed_fields is empty."""
        gear_item = MagicMock()
        saved = MagicMock()
        saved.id = uuid4()
        mock_repo.save.return_value = saved
        changed_fields: dict[str, Any] = {}

        result = await service.update(
            gear_item, changed_fields=changed_fields, transaction=mock_transaction
        )

        assert result is saved
        mock_repo.save.assert_awaited_once_with(gear_item)
        mock_publisher.publish.assert_not_awaited()


class TestDelete:
    """Test the delete unit of work."""

    @pytest.mark.asyncio
    async def test_delete_delegates_to_repo(self, service, mock_repo, mock_transaction):
        """delete delegates to the repo with the given id."""
        gear_item_id = str(uuid4())

        await service.delete(gear_item_id, transaction=mock_transaction)

        mock_repo.delete.assert_awaited_once_with(gear_item_id)
