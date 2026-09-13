"""Unit tests for RouteService."""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from core_shared.models import Route
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    RouteNotFoundError,
    RouteValidationError,
)

from app.core.journal.services.route_service import RouteService
from app.core.journal.utils.route_edits import RouteEdit


def create_test_route(
    route_id: UUID | None = None,
    journal_id: int = 1,
    name: str = "Test Route",
    description: str | None = None,
    gpx_data: str | None = None,
) -> Route:
    """Create a test route."""
    return Route(
        id=route_id,
        journal_id=journal_id,
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
    """The service owns the merge.

    It locks the row, applies the edit to what it read under the lock, and
    computes the changed fields itself, so two concurrent partial edits cannot
    silently revert each other or record half of what happened.
    """

    @pytest.mark.asyncio
    async def test_update_route_merges_the_edit_into_the_locked_row(
        self, route_service, mock_route_repo, mock_event_publisher, mock_transaction
    ):
        route_id = uuid4()
        mock_route_repo.find_by_id_for_update.return_value = create_test_route(
            route_id=route_id, name="Old", description="kept"
        )
        mock_route_repo.save.side_effect = lambda route: route

        result = await route_service.update_route(
            route_id,
            RouteEdit(name="New"),
            mock_transaction,
            changed_by="mcp",
            source=Provenance.MCP,
        )

        mock_route_repo.find_by_id_for_update.assert_awaited_once_with(route_id)
        mock_route_repo.find_by_id.assert_not_called()
        saved = mock_route_repo.save.await_args.args[0]
        assert (saved.id, saved.name, saved.description) == (route_id, "New", "kept")
        assert result is saved

        event = mock_event_publisher.publish.await_args.args[0]
        assert event.event_type == "RouteUpdated"
        assert event.event_data["changed_fields"] == {"name": ("Old", "New")}
        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_update_route_not_found(
        self, route_service, mock_route_repo, mock_event_publisher, mock_transaction
    ):
        mock_route_repo.find_by_id_for_update.return_value = None

        with pytest.raises(RouteNotFoundError):
            await route_service.update_route(
                uuid4(), RouteEdit(name="X"), mock_transaction
            )

        mock_route_repo.save.assert_not_called()
        mock_event_publisher.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_invalid_edit_writes_nothing(
        self, route_service, mock_route_repo, mock_event_publisher, mock_transaction
    ):
        route_id = uuid4()
        mock_route_repo.find_by_id_for_update.return_value = create_test_route(
            route_id=route_id
        )

        with pytest.raises(RouteValidationError) as exc_info:
            await route_service.update_route(
                route_id, RouteEdit(gpx_data="not xml"), mock_transaction
            )

        assert exc_info.value.field == "gpx_data"
        mock_route_repo.save.assert_not_called()
        mock_event_publisher.publish.assert_not_called()


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
        # Act
        await route_service.delete_route(route_id, mock_transaction)

        # Assert
        mock_route_repo.find_by_id.assert_called_once_with(route_id)
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
    async def test_get_routes_by_journal(self, route_service, mock_route_repo):
        """Test getting all routes for a user."""
        # Arrange
        routes = [
            create_test_route(route_id=uuid4(), name="Route 1"),
            create_test_route(route_id=uuid4(), name="Route 2"),
        ]

        mock_route_repo.find_by_journal_id.return_value = routes

        # Act
        result = await route_service.get_routes_by_journal(1)

        # Assert
        assert result == routes
        mock_route_repo.find_by_journal_id.assert_called_once_with(1)
