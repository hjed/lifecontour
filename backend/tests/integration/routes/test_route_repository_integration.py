"""Integration tests for SqlRouteRepository with real database."""

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

if TYPE_CHECKING:
    from core_shared.models.journals import Journal

    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

from app.core.journal.adapters.sql.route_repository import SqlRouteRepository


@pytest_asyncio.fixture
async def route_repository(
    async_connection: AsyncConnection,
) -> SqlRouteRepository:
    return SqlRouteRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def test_journal(journal_repository: SqlJournalRepository) -> Journal:
    """Create a test journal."""
    from datetime import UTC, datetime, timedelta

    from core_shared.models.journals import EventDateRange, Journal

    now = datetime.now(UTC)
    journal = Journal(
        user_id="test-user-123",
        title="Test Journal",
        content="Test content",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=1),
        ),
    )
    return await journal_repository.save(journal)


def create_test_route(
    journal_id: int | None = 1,
    name: str = "Test Route",
    description: str | None = "A test route",
    gpx_data: str | None = None,
) -> Route:
    """Helper to create a test route."""
    assert journal_id is not None
    return Route(
        journal_id=journal_id,
        name=name,
        description=description,
        gpx_data=gpx_data,
    )


@pytest.mark.integration
class TestRouteRepositorySave:
    """Test route save operations."""

    async def test_save_creates_new_route(
        self, route_repository: SqlRouteRepository, test_journal: Journal
    ):
        """Test creating a new route."""
        route = create_test_route(journal_id=test_journal.id)

        saved = await route_repository.save(route)

        assert saved.id is not None
        assert saved.journal_id == test_journal.id
        assert saved.name == "Test Route"
        assert saved.description == "A test route"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_updates_existing_route(
        self, route_repository: SqlRouteRepository, test_journal: Journal
    ):
        """Test updating an existing route."""
        import asyncio

        route = create_test_route(journal_id=test_journal.id)
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

    async def test_save_route_with_gpx_data(
        self, route_repository: SqlRouteRepository, test_journal: Journal
    ):
        """Test saving a route with GPX data."""
        gpx_data = (
            '<?xml version="1.0"?><gpx version="1.1"><trk><name>Test</name></trk></gpx>'
        )
        route = create_test_route(journal_id=test_journal.id, gpx_data=gpx_data)

        saved = await route_repository.save(route)

        assert saved.id is not None
        assert saved.gpx_data == gpx_data


@pytest.mark.integration
class TestRouteRepositoryFindById:
    """Test route find by ID operations."""

    async def test_find_by_id_returns_route(
        self, route_repository: SqlRouteRepository, test_journal: Journal
    ):
        """Test finding a route by ID."""
        route = create_test_route(journal_id=test_journal.id)
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
class TestRouteRepositoryFindByIdForUpdate:
    """The locking read ``RouteService.update_route`` merges an edit into.

    The ``FOR UPDATE`` lock itself cannot be exercised here: a second
    connection would commit outside the test's savepoint.
    """

    async def test_returns_the_route(
        self, route_repository: SqlRouteRepository, test_journal: Journal
    ):
        gpx_data = '<?xml version="1.0"?><gpx version="1.1"></gpx>'
        saved = await route_repository.save(
            create_test_route(journal_id=test_journal.id, gpx_data=gpx_data)
        )
        assert saved.id is not None

        found = await route_repository.find_by_id_for_update(saved.id)

        assert found is not None
        assert (found.id, found.journal_id, found.name, found.gpx_data) == (
            saved.id,
            test_journal.id,
            "Test Route",
            gpx_data,
        )
        assert found.created_at == saved.created_at

    async def test_returns_none_for_missing(self, route_repository: SqlRouteRepository):
        assert await route_repository.find_by_id_for_update(uuid4()) is None


@pytest.mark.integration
class TestRouteRepositoryDelete:
    """Test route delete operations."""

    async def test_delete_removes_route(
        self, route_repository: SqlRouteRepository, test_journal: Journal
    ):
        """Test deleting a route."""
        route = create_test_route(journal_id=test_journal.id)
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
