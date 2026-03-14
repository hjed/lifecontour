"""Integration tests for SqlBushwalkingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import BushwalkingData, EventDateRange, Journal
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository


@pytest_asyncio.fixture
async def bushwalking_repository(
    async_connection: AsyncConnection,
) -> SqlBushwalkingDataRepository:
    """Create a bushwalking data repository for testing."""
    return SqlBushwalkingDataRepository(async_connection)


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
        title="Blue Mountains Walk",
        content="Day walk in the Blue Mountains",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=5),
        ),
    )
    return await journal_repository.save(journal)


@pytest_asyncio.fixture
async def test_route(route_repository: SqlRouteRepository) -> Route:
    """Create a test route."""
    route = Route(
        user_id="test-user-123",
        name="Grand Canyon Walk",
        description="A scenic walk",
    )
    return await route_repository.save(route)


@pytest.mark.integration
class TestBushwalkingDataRepositorySave:
    """Test bushwalking data save operations."""

    async def test_save_creates_new_bushwalking_data(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
        test_journal: Journal,
    ):
        """Test creating bushwalking data (adding BUSHWALKING type to journal)."""
        data = BushwalkingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            track_grading="Grade 3",
        )

        saved = await bushwalking_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.track_grading == "Grade 3"
        assert saved.route_id is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
        test_journal: Journal,
    ):
        """Test creating bushwalking data with only required fields."""
        data = BushwalkingData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await bushwalking_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.route_id is None
        assert saved.track_grading is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_route_id(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test creating bushwalking data with a route reference."""
        data = BushwalkingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
            track_grading="Grade 2",
        )

        saved = await bushwalking_repository.save(data)

        assert saved.route_id == test_route.id
        assert saved.track_grading == "Grade 2"

    async def test_save_updates_existing_data(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing bushwalking data."""
        data = BushwalkingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            track_grading="Grade 2",
        )
        await bushwalking_repository.save(data)

        updated_data = BushwalkingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            track_grading="Grade 4",
        )
        saved = await bushwalking_repository.save(updated_data)

        assert saved.track_grading == "Grade 4"


@pytest.mark.integration
class TestBushwalkingDataRepositoryFind:
    """Test bushwalking data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
        test_journal: Journal,
    ):
        """Test finding bushwalking data by journal ID."""
        data = BushwalkingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            track_grading="Grade 3",
        )
        await bushwalking_repository.save(data)

        found = await bushwalking_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.track_grading == "Grade 3"

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
    ):
        """Test finding bushwalking data returns None when not found."""
        found = await bushwalking_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_route_id(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test that route_id is correctly persisted and retrieved."""
        data = BushwalkingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
        )
        await bushwalking_repository.save(data)

        found = await bushwalking_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.route_id == test_route.id


@pytest.mark.integration
class TestBushwalkingDataRepositoryDelete:
    """Test bushwalking data delete operations."""

    async def test_delete_removes_data(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
        test_journal: Journal,
    ):
        """Test deleting bushwalking data."""
        data = BushwalkingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            track_grading="Grade 1",
        )
        await bushwalking_repository.save(data)

        await bushwalking_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await bushwalking_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        bushwalking_repository: SqlBushwalkingDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await bushwalking_repository.delete(99999)
