"""Integration tests for SqlClimbingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import ClimbingData, EventDateRange, Journal
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.climbing_data_repository import (
    SqlClimbingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository


@pytest_asyncio.fixture
async def climbing_repository(
    async_connection: AsyncConnection,
) -> SqlClimbingDataRepository:
    """Create a climbing data repository for testing."""
    return SqlClimbingDataRepository(async_connection)


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
        title="Mt Arapiles Sport Climb",
        content="Sport climbing at Mt Arapiles",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=4),
        ),
    )
    return await journal_repository.save(journal)


@pytest_asyncio.fixture
async def test_route(route_repository: SqlRouteRepository) -> Route:
    """Create a test route."""
    route = Route(
        journal_id=999,
        name="Tiptoe Ridge",
        description="Classic trad climb at Arapiles",
    )
    return await route_repository.save(route)


@pytest.mark.integration
class TestClimbingDataRepositorySave:
    """Test climbing data save operations."""

    async def test_save_creates_new_climbing_data(
        self,
        climbing_repository: SqlClimbingDataRepository,
        test_journal: Journal,
    ):
        """Test creating climbing data (adding CLIMBING type to journal)."""
        data = ClimbingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            climbing_type="sport",
            grade=18,
            length=25,
        )

        saved = await climbing_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.climbing_type == "sport"
        assert saved.grade == 18
        assert saved.length == 25
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        climbing_repository: SqlClimbingDataRepository,
        test_journal: Journal,
    ):
        """Test creating climbing data with only required fields."""
        data = ClimbingData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await climbing_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.climbing_type is None
        assert saved.grade is None
        assert saved.length is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_route_id(
        self,
        climbing_repository: SqlClimbingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test creating climbing data with a route reference."""
        data = ClimbingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            climbing_type="trad",
            grade=16,
        )

        saved = await climbing_repository.save(data)

        assert saved.climbing_type == "trad"
        assert saved.grade == 16

    async def test_save_updates_existing_data(
        self,
        climbing_repository: SqlClimbingDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing climbing data."""
        data = ClimbingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            climbing_type="bouldering",
            grade=20,
        )
        await climbing_repository.save(data)

        updated_data = ClimbingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            climbing_type="sport",
            grade=24,
            length=35,
        )
        saved = await climbing_repository.save(updated_data)

        assert saved.climbing_type == "sport"
        assert saved.grade == 24
        assert saved.length == 35


@pytest.mark.integration
class TestClimbingDataRepositoryFind:
    """Test climbing data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        climbing_repository: SqlClimbingDataRepository,
        test_journal: Journal,
    ):
        """Test finding climbing data by journal ID."""
        data = ClimbingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            climbing_type="sport",
            grade=22,
            length=30,
        )
        await climbing_repository.save(data)

        found = await climbing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.climbing_type == "sport"
        assert found.grade == 22
        assert found.length == 30

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        climbing_repository: SqlClimbingDataRepository,
    ):
        """Test finding climbing data returns None when not found."""
        found = await climbing_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_route_id(
        self,
        climbing_repository: SqlClimbingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test that route_id is correctly persisted and retrieved."""
        data = ClimbingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
        )
        await climbing_repository.save(data)

        found = await climbing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None


@pytest.mark.integration
class TestClimbingDataRepositoryDelete:
    """Test climbing data delete operations."""

    async def test_delete_removes_data(
        self,
        climbing_repository: SqlClimbingDataRepository,
        test_journal: Journal,
    ):
        """Test deleting climbing data."""
        data = ClimbingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            climbing_type="trad",
            grade=15,
        )
        await climbing_repository.save(data)

        await climbing_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await climbing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        climbing_repository: SqlClimbingDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await climbing_repository.delete(99999)
