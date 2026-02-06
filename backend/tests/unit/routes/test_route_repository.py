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
            user_id="test_user",
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
            user_id=sample_route.user_id,
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

    async def test_get_all_returns_routes_for_user(self, mock_repository, sample_route):
        """Test get_all returns all routes for a user."""
        routes = [sample_route]
        mock_repository.get_all.return_value = routes

        result = await mock_repository.get_all("test_user", limit=100, offset=0)

        assert result == routes
        mock_repository.get_all.assert_called_once_with(
            "test_user", limit=100, offset=0
        )

    async def test_get_all_with_pagination(self, mock_repository):
        """Test get_all supports pagination."""
        mock_repository.get_all.return_value = []

        await mock_repository.get_all("test_user", limit=50, offset=10)

        mock_repository.get_all.assert_called_once_with(
            "test_user", limit=50, offset=10
        )

    async def test_check_usage_in_journals_returns_true_when_used(
        self, mock_repository
    ):
        """Test check_usage_in_journals returns True when route is used."""
        route_id = uuid4()
        mock_repository.check_usage_in_journals.return_value = True

        result = await mock_repository.check_usage_in_journals(route_id)

        assert result is True
        mock_repository.check_usage_in_journals.assert_called_once_with(route_id)

    async def test_check_usage_in_journals_returns_false_when_not_used(
        self, mock_repository
    ):
        """Test check_usage_in_journals returns False when route is not used."""
        route_id = uuid4()
        mock_repository.check_usage_in_journals.return_value = False

        result = await mock_repository.check_usage_in_journals(route_id)

        assert result is False
        mock_repository.check_usage_in_journals.assert_called_once_with(route_id)

    async def test_get_count_returns_total_routes(self, mock_repository):
        """Test get_count returns total number of routes for a user."""
        mock_repository.get_count.return_value = 5

        result = await mock_repository.get_count("test_user")

        assert result == 5
        mock_repository.get_count.assert_called_once_with("test_user")
