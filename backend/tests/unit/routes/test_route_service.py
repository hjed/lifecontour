"""Unit tests for RouteService."""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from core_shared.models import Route

from app.core.journal.models.exceptions import (
    RouteInUseError,
    RouteNotFoundError,
    RouteValidationError,
)
from app.core.journal.services.route_service import RouteService


def create_test_route(
    route_id: UUID | None = None,
    user_id: str = "test-user-123",
    name: str = "Test Route",
    description: str | None = None,
    gpx_data: str | None = None,
) -> Route:
    """Create a test route."""
    return Route(
        id=route_id,
        user_id=user_id,
        name=name,
        description=description,
        gpx_data=gpx_data,
    )


@pytest.fixture
def mock_route_repo():
    """Create mock route repository."""
    return AsyncMock()


@pytest.fixture
def mock_event_publisher():
    """Create mock event publisher."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create mock transaction."""
    return AsyncMock()


@pytest.fixture
def route_service(mock_route_repo, mock_event_publisher):
    """Create RouteService instance."""
    return RouteService(mock_route_repo, mock_event_publisher)


class TestRouteServiceCreate:
    """Test route creation."""

    @pytest.mark.asyncio
    async def test_create_route_success(
        self, route_service, mock_route_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful route creation."""
        # Arrange
        route = create_test_route()
        saved_route = create_test_route(route_id=uuid4())

        mock_route_repo.save.return_value = saved_route

        # Act
        result = await route_service.create_route(route, mock_transaction)

        # Assert
        assert result == saved_route
        mock_route_repo.save.assert_called_once_with(route)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_route_with_id_fails(self, route_service, mock_transaction):
        """Test that creating a route with an existing ID fails."""
        # Arrange
        route = create_test_route(route_id=uuid4())  # Route already has an ID

        # Act & Assert
        with pytest.raises(RouteValidationError) as exc_info:
            await route_service.create_route(route, mock_transaction)

        assert "existing ID" in str(exc_info.value)


class TestRouteServiceUpdate:
    """Test route updates."""

    @pytest.mark.asyncio
    async def test_update_route_success(
        self, route_service, mock_route_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful route update."""
        # Arrange
        route_id = uuid4()
        route = create_test_route(route_id=route_id, name="Updated Route")
        changed_fields = {"name": "Updated Route"}

        mock_route_repo.find_by_id.return_value = route
        mock_route_repo.save.return_value = route

        # Act
        result = await route_service.update_route(
            route, changed_fields, mock_transaction
        )

        # Assert
        assert result == route
        mock_route_repo.find_by_id.assert_called_once_with(route_id)
        mock_route_repo.save.assert_called_once_with(route)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_route_not_found(
        self, route_service, mock_route_repo, mock_transaction
    ):
        """Test update fails when route doesn't exist."""
        # Arrange
        route_id = uuid4()
        route = create_test_route(route_id=route_id)

        mock_route_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(RouteNotFoundError):
            await route_service.update_route(route, {}, mock_transaction)


class TestRouteServiceDelete:
    """Test route deletion."""

    @pytest.mark.asyncio
    async def test_delete_route_success(
        self, route_service, mock_route_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful route deletion."""
        # Arrange
        route_id = uuid4()
        route = create_test_route(route_id=route_id)

        mock_route_repo.find_by_id.return_value = route
        mock_route_repo.check_usage_in_journals.return_value = False

        # Act
        await route_service.delete_route(route_id, mock_transaction)

        # Assert
        mock_route_repo.find_by_id.assert_called_once_with(route_id)
        mock_route_repo.check_usage_in_journals.assert_called_once_with(route_id)
        mock_route_repo.delete.assert_called_once_with(route_id)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_route_not_found(
        self, route_service, mock_route_repo, mock_transaction
    ):
        """Test delete fails when route doesn't exist."""
        # Arrange
        route_id = uuid4()

        mock_route_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(RouteNotFoundError):
            await route_service.delete_route(route_id, mock_transaction)

    @pytest.mark.asyncio
    async def test_delete_route_in_use(
        self, route_service, mock_route_repo, mock_transaction
    ):
        """Test delete fails when route is in use."""
        # Arrange
        route_id = uuid4()
        route = create_test_route(route_id=route_id)

        mock_route_repo.find_by_id.return_value = route
        mock_route_repo.check_usage_in_journals.return_value = True

        # Act & Assert
        with pytest.raises(RouteInUseError):
            await route_service.delete_route(route_id, mock_transaction)


class TestRouteServiceGet:
    """Test route retrieval."""

    @pytest.mark.asyncio
    async def test_get_route_success(self, route_service, mock_route_repo):
        """Test successful route retrieval."""
        # Arrange
        route_id = uuid4()
        route = create_test_route(route_id=route_id)

        mock_route_repo.find_by_id.return_value = route

        # Act
        result = await route_service.get_route(route_id)

        # Assert
        assert result == route
        mock_route_repo.find_by_id.assert_called_once_with(route_id)

    @pytest.mark.asyncio
    async def test_get_route_not_found(self, route_service, mock_route_repo):
        """Test get fails when route doesn't exist."""
        # Arrange
        route_id = uuid4()

        mock_route_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(RouteNotFoundError):
            await route_service.get_route(route_id)


class TestRouteServiceList:
    """Test route listing."""

    @pytest.mark.asyncio
    async def test_get_routes_for_user(self, route_service, mock_route_repo):
        """Test getting all routes for a user."""
        # Arrange
        user_id = "test-user-123"
        routes = [
            create_test_route(route_id=uuid4(), name="Route 1"),
            create_test_route(route_id=uuid4(), name="Route 2"),
        ]

        mock_route_repo.get_all.return_value = routes

        # Act
        result = await route_service.get_routes_for_user(user_id, limit=10, offset=0)

        # Assert
        assert result == routes
        mock_route_repo.get_all.assert_called_once_with(user_id, 10, 0)

    @pytest.mark.asyncio
    async def test_get_routes_for_user_with_name_filter(
        self, route_service, mock_route_repo
    ):
        """Test getting filtered routes for a user."""
        user_id = "test-user-123"
        routes = [create_test_route(route_id=uuid4(), name="Grand Canyon")]

        mock_route_repo.get_all.return_value = routes

        result = await route_service.get_routes_for_user(
            user_id, name="grand", limit=10, offset=0
        )

        assert result == routes
        mock_route_repo.get_all.assert_called_once_with(user_id, 10, 0, "grand")

    @pytest.mark.asyncio
    async def test_get_route_count(self, route_service, mock_route_repo):
        """Test getting route count for a user."""
        # Arrange
        user_id = "test-user-123"

        mock_route_repo.get_count.return_value = 5

        # Act
        result = await route_service.get_route_count(user_id)

        # Assert
        assert result == 5
        mock_route_repo.get_count.assert_called_once_with(user_id)

    @pytest.mark.asyncio
    async def test_get_route_count_with_name_filter(
        self, route_service, mock_route_repo
    ):
        """Test getting filtered route count for a user."""
        user_id = "test-user-123"

        mock_route_repo.get_count.return_value = 2

        result = await route_service.get_route_count(user_id, name="grand")

        assert result == 2
        mock_route_repo.get_count.assert_called_once_with(user_id, "grand")
