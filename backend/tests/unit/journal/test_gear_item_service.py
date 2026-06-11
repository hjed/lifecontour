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


def _gear(**fields: Any) -> MagicMock:
    """A gear-item mock with explicit tracked-field values."""
    item = MagicMock()
    defaults = {
        "name": "Tent",
        "model": "X1",
        "serial_number": "SN1",
        "purchase_date": None,
        "manufacturer": "Acme",
    }
    defaults.update(fields)
    for k, v in defaults.items():
        setattr(item, k, v)
    return item


class TestUpdate:
    """Test the update unit of work."""

    @pytest.mark.asyncio
    async def test_update_publishes_event_with_computed_diff(
        self, service, mock_repo, mock_publisher, mock_transaction
    ):
        """update computes changed_fields against the persisted state and emits it."""
        gear_item = MagicMock()
        existing = _gear(name="Old Tent")
        saved = _gear(name="New Tent")
        saved.id = uuid4()
        mock_repo.find_by_id.return_value = existing
        mock_repo.save.return_value = saved

        result = await service.update(
            gear_item, transaction=mock_transaction, changed_by="mcp"
        )

        assert result is saved
        mock_repo.save.assert_awaited_once_with(gear_item)
        mock_publisher.publish.assert_awaited_once()
        event = mock_publisher.publish.await_args.args[0]
        assert isinstance(event, GearItemUpdated)
        # diff computed in the service, not supplied by the caller
        assert event.event_data["changed_fields"] == {"name": ("Old Tent", "New Tent")}
        assert event.event_data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_update_skips_event_when_nothing_changed(
        self, service, mock_repo, mock_publisher, mock_transaction
    ):
        """update saves but publishes no event when no tracked field changed."""
        gear_item = MagicMock()
        existing = _gear()
        saved = _gear()
        saved.id = uuid4()
        mock_repo.find_by_id.return_value = existing
        mock_repo.save.return_value = saved

        result = await service.update(gear_item, transaction=mock_transaction)

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
