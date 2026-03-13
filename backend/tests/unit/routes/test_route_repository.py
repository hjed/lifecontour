"""Unit tests for RouteRepository interface."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core_shared.models.route import Route

from app.core.journal.models.repositories import RouteRepository


@pytest.mark.unit
class TestRouteRepository:
    """Test RouteRepository interface methods."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository for testing."""
        return AsyncMock(spec=RouteRepository)

    @pytest.fixture
    def sample_route(self):
        """Create a sample route for testing."""
        return Route(
            id=uuid4(),
            journal_id=1,
            name="Test Route",
            description="A test route",
        )

    async def test_find_by_id_returns_route(self, mock_repository, sample_route):
        """Test find_by_id returns a route when found."""
        mock_repository.find_by_id.return_value = sample_route

        result = await mock_repository.find_by_id(sample_route.id)

        assert result == sample_route
        mock_repository.find_by_id.assert_called_once_with(sample_route.id)

    async def test_find_by_id_returns_none_when_not_found(self, mock_repository):
        """Test find_by_id returns None when route not found."""
        mock_repository.find_by_id.return_value = None

        result = await mock_repository.find_by_id(uuid4())

        assert result is None

    async def test_save_creates_new_route(self, mock_repository, sample_route):
        """Test save creates a new route."""
        mock_repository.save.return_value = sample_route

        result = await mock_repository.save(sample_route)

        assert result == sample_route
        mock_repository.save.assert_called_once_with(sample_route)

    async def test_save_updates_existing_route(self, mock_repository, sample_route):
        """Test save updates an existing route."""
        updated_route = Route(
            id=sample_route.id,
            journal_id=sample_route.journal_id,
            name="Updated Route Name",
            description=sample_route.description,
        )
        mock_repository.save.return_value = updated_route

        result = await mock_repository.save(updated_route)

        assert result.name == "Updated Route Name"
        mock_repository.save.assert_called_once_with(updated_route)

    async def test_delete_removes_route(self, mock_repository):
        """Test delete removes a route."""
        route_id = uuid4()
        mock_repository.delete.return_value = None

        await mock_repository.delete(route_id)

        mock_repository.delete.assert_called_once_with(route_id)

    async def test_find_by_journal_id_returns_routes(
        self, mock_repository, sample_route
    ):
        """Test find_by_journal_id returns all routes for a journal."""
        routes = [sample_route]
        mock_repository.find_by_journal_id.return_value = routes

        result = await mock_repository.find_by_journal_id(1)

        assert result == routes
        mock_repository.find_by_journal_id.assert_called_once_with(1)
