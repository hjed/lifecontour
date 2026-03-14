"""Integration tests for SqlJoggingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, JoggingData, Journal
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.jogging_data_repository import (
    SqlJoggingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository


@pytest_asyncio.fixture
async def jogging_repository(
    async_connection: AsyncConnection,
) -> SqlJoggingDataRepository:
    """Create a jogging data repository for testing."""
    return SqlJoggingDataRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def route_repository(
    async_connection: AsyncConnection,
) -> SqlRouteRepository:
    """Create a route repository for testing."""
    return SqlRouteRepository(async_connection)


@pytest_asyncio.fixture
async def test_journal(
    journal_repository: SqlJournalRepository,
) -> Journal:
    """Create a test journal."""
    now = datetime.now(UTC)
    journal = Journal(
        user_id="test-user-123",
        title="Morning Jog",
        content="5km jog around the park",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(minutes=30),
        ),
    )
    return await journal_repository.save(journal)


@pytest_asyncio.fixture
async def test_route(route_repository: SqlRouteRepository) -> Route:
    """Create a test route."""
    route = Route(
        user_id="test-user-123",
        name="Park Loop",
        description="5km loop around the park",
    )
    return await route_repository.save(route)


@pytest.mark.integration
class TestJoggingDataRepositorySave:
    """Test jogging data save operations."""

    async def test_save_creates_new_jogging_data(
        self,
        jogging_repository: SqlJoggingDataRepository,
        test_journal: Journal,
    ):
        """Test creating jogging data (adding JOGGING type to journal)."""
        data = JoggingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            pace=360,  # 6 min/km in seconds
        )

        saved = await jogging_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.pace == 360
        assert saved.route_id is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        jogging_repository: SqlJoggingDataRepository,
        test_journal: Journal,
    ):
        """Test creating jogging data with only required fields."""
        data = JoggingData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await jogging_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.route_id is None
        assert saved.pace is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_route_id(
        self,
        jogging_repository: SqlJoggingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test creating jogging data with a route reference."""
        data = JoggingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
            pace=300,  # 5 min/km
        )

        saved = await jogging_repository.save(data)

        assert saved.route_id == test_route.id
        assert saved.pace == 300

    async def test_save_updates_existing_data(
        self,
        jogging_repository: SqlJoggingDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing jogging data."""
        data = JoggingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            pace=360,
        )
        await jogging_repository.save(data)

        updated_data = JoggingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            pace=320,
        )
        saved = await jogging_repository.save(updated_data)

        assert saved.pace == 320


@pytest.mark.integration
class TestJoggingDataRepositoryFind:
    """Test jogging data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        jogging_repository: SqlJoggingDataRepository,
        test_journal: Journal,
    ):
        """Test finding jogging data by journal ID."""
        data = JoggingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            pace=360,
        )
        await jogging_repository.save(data)

        found = await jogging_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.pace == 360

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        jogging_repository: SqlJoggingDataRepository,
    ):
        """Test finding jogging data returns None when not found."""
        found = await jogging_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_route_id(
        self,
        jogging_repository: SqlJoggingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test that route_id is correctly persisted and retrieved."""
        data = JoggingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
        )
        await jogging_repository.save(data)

        found = await jogging_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.route_id == test_route.id


@pytest.mark.integration
class TestJoggingDataRepositoryDelete:
    """Test jogging data delete operations."""

    async def test_delete_removes_data(
        self,
        jogging_repository: SqlJoggingDataRepository,
        test_journal: Journal,
    ):
        """Test deleting jogging data."""
        data = JoggingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            pace=360,
        )
        await jogging_repository.save(data)

        await jogging_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await jogging_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        jogging_repository: SqlJoggingDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await jogging_repository.delete(99999)
