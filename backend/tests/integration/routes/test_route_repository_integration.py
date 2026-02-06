"""Integration tests for SqlRouteRepository with real database."""

from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.route_repository import SqlRouteRepository


@pytest_asyncio.fixture
async def route_repository(
    async_connection: AsyncConnection,
) -> SqlRouteRepository:
    """Create a route repository for testing."""
    return SqlRouteRepository(async_connection)


def create_test_route(
    user_id: str = "test-user-123",
    name: str = "Test Route",
    description: str | None = "A test route",
    gpx_data: str | None = None,
) -> Route:
    """Helper to create a test route."""
    return Route(
        user_id=user_id,
        name=name,
        description=description,
        gpx_data=gpx_data,
    )


@pytest.mark.integration
class TestRouteRepositorySave:
    """Test route save operations."""

    async def test_save_creates_new_route(self, route_repository: SqlRouteRepository):
        """Test creating a new route."""
        route = create_test_route()

        saved = await route_repository.save(route)

        assert saved.id is not None
        assert saved.user_id == "test-user-123"
        assert saved.name == "Test Route"
        assert saved.description == "A test route"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_updates_existing_route(
        self, route_repository: SqlRouteRepository
    ):
        """Test updating an existing route."""
        import asyncio

        route = create_test_route()
        saved = await route_repository.save(route)

        # Save the original updated_at timestamp before updating
        original_updated_at = saved.updated_at

        # Add a small delay to ensure updated_at will be different
        await asyncio.sleep(0.01)

        # Update the route
        saved.name = "Updated Route Name"
        saved.description = "Updated description"

        updated = await route_repository.save(saved)

        assert updated.id == saved.id
        assert updated.name == "Updated Route Name"
        assert updated.description == "Updated description"
        assert updated.updated_at is not None
        assert original_updated_at is not None
        assert updated.updated_at > original_updated_at

    async def test_save_route_with_gpx_data(self, route_repository: SqlRouteRepository):
        """Test saving a route with GPX data."""
        gpx_data = (
            '<?xml version="1.0"?><gpx version="1.1"><trk><name>Test</name></trk></gpx>'
        )
        route = create_test_route(gpx_data=gpx_data)

        saved = await route_repository.save(route)

        assert saved.id is not None
        assert saved.gpx_data == gpx_data


@pytest.mark.integration
class TestRouteRepositoryFindById:
    """Test route find by ID operations."""

    async def test_find_by_id_returns_route(self, route_repository: SqlRouteRepository):
        """Test finding a route by ID."""
        route = create_test_route()
        saved = await route_repository.save(route)

        found = await route_repository.find_by_id(saved.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.id == saved.id
        assert found.name == saved.name

    async def test_find_by_id_returns_none_for_missing(
        self, route_repository: SqlRouteRepository
    ):
        """Test finding a non-existent route returns None."""
        found = await route_repository.find_by_id(uuid4())

        assert found is None


@pytest.mark.integration
class TestRouteRepositoryDelete:
    """Test route delete operations."""

    async def test_delete_removes_route(self, route_repository: SqlRouteRepository):
        """Test deleting a route."""
        route = create_test_route()
        saved = await route_repository.save(route)

        await route_repository.delete(saved.id)  # type: ignore[arg-type]

        found = await route_repository.find_by_id(saved.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_route_does_not_error(
        self, route_repository: SqlRouteRepository
    ):
        """Test deleting a non-existent route doesn't raise an error."""
        # Should not raise an exception
        await route_repository.delete(uuid4())


@pytest.mark.integration
class TestRouteRepositoryQueries:
    """Test route query operations."""

    async def test_get_all_returns_user_routes(
        self, route_repository: SqlRouteRepository
    ):
        """Test getting all routes for a user."""
        user1_r1 = create_test_route(user_id="user-1", name="User 1 Route 1")
        user1_r2 = create_test_route(user_id="user-1", name="User 1 Route 2")
        user2_r1 = create_test_route(user_id="user-2", name="User 2 Route 1")

        await route_repository.save(user1_r1)
        await route_repository.save(user1_r2)
        await route_repository.save(user2_r1)

        user1_routes = await route_repository.get_all("user-1")

        assert len(user1_routes) == 2
        assert all(r.user_id == "user-1" for r in user1_routes)

    async def test_get_all_with_pagination(self, route_repository: SqlRouteRepository):
        """Test getting routes with pagination."""
        # Create 5 routes for the same user
        for i in range(5):
            route = create_test_route(user_id="user-1", name=f"Route {i}")
            await route_repository.save(route)

        # Get first 2 routes
        page1 = await route_repository.get_all("user-1", limit=2, offset=0)
        assert len(page1) == 2

        # Get next 2 routes
        page2 = await route_repository.get_all("user-1", limit=2, offset=2)
        assert len(page2) == 2

        # Ensure they're different routes
        page1_ids = {r.id for r in page1}
        page2_ids = {r.id for r in page2}
        assert page1_ids.isdisjoint(page2_ids)

    async def test_get_count_returns_total_routes(
        self, route_repository: SqlRouteRepository
    ):
        """Test getting total count of routes for a user."""
        # Create 3 routes for user-1
        for i in range(3):
            route = create_test_route(user_id="user-1", name=f"Route {i}")
            await route_repository.save(route)

        # Create 2 routes for user-2
        for i in range(2):
            route = create_test_route(user_id="user-2", name=f"Route {i}")
            await route_repository.save(route)

        count_user1 = await route_repository.get_count("user-1")
        count_user2 = await route_repository.get_count("user-2")

        assert count_user1 == 3
        assert count_user2 == 2

    async def test_get_count_returns_zero_for_no_routes(
        self, route_repository: SqlRouteRepository
    ):
        """Test getting count returns 0 when user has no routes."""
        count = await route_repository.get_count("nonexistent-user")
        assert count == 0


@pytest.mark.integration
class TestRouteRepositoryUsageCheck:
    """Test route usage checking in journals."""

    async def test_check_usage_returns_false_when_not_used(
        self, route_repository: SqlRouteRepository
    ):
        """Test check_usage_in_journals returns False when route is not used.

        Note: This currently always returns False since activity-specific tables
        (journal_bushwalking_data, journal_kayaking_data, etc.) don't exist yet.
        This test will be updated when those tables are implemented in future iterations.
        """
        route = create_test_route()
        saved = await route_repository.save(route)

        is_used = await route_repository.check_usage_in_journals(saved.id)  # type: ignore[arg-type]

        assert is_used is False
