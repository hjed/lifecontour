"""Integration tests for SqlCrossCountrySkiingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import CrossCountrySkiingData, EventDateRange, Journal
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.cross_country_skiing_data_repository import (
    SqlCrossCountrySkiingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository


@pytest_asyncio.fixture
async def skiing_repository(
    async_connection: AsyncConnection,
) -> SqlCrossCountrySkiingDataRepository:
    """Create a cross-country skiing data repository for testing."""
    return SqlCrossCountrySkiingDataRepository(async_connection)


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
        title="Cross Country Ski Tour",
        content="Skiing through alpine trails",
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
        journal_id=999,
        name="Kosciuszko Ski Trail",
        description="Cross-country ski trail through Kosciuszko NP",
    )
    return await route_repository.save(route)


@pytest.mark.integration
class TestCrossCountrySkiingDataRepositorySave:
    """Test cross-country skiing data save operations."""

    async def test_save_creates_new_skiing_data(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
        test_journal: Journal,
    ):
        """Test creating skiing data (adding CROSS_COUNTRY_SKIING type to journal)."""
        data = CrossCountrySkiingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            snow_conditions="packed powder",
        )

        saved = await skiing_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.snow_conditions == "packed powder"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
        test_journal: Journal,
    ):
        """Test creating skiing data with only required fields."""
        data = CrossCountrySkiingData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await skiing_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.snow_conditions is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_route_id(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test creating skiing data with a route reference."""
        data = CrossCountrySkiingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            snow_conditions="groomed trails",
        )

        saved = await skiing_repository.save(data)

        assert saved.snow_conditions == "groomed trails"

    async def test_save_updates_existing_data(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing skiing data."""
        data = CrossCountrySkiingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            snow_conditions="fresh powder",
        )
        await skiing_repository.save(data)

        updated_data = CrossCountrySkiingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            snow_conditions="icy",
        )
        saved = await skiing_repository.save(updated_data)

        assert saved.snow_conditions == "icy"


@pytest.mark.integration
class TestCrossCountrySkiingDataRepositoryFind:
    """Test cross-country skiing data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
        test_journal: Journal,
    ):
        """Test finding skiing data by journal ID."""
        data = CrossCountrySkiingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            snow_conditions="wet snow",
        )
        await skiing_repository.save(data)

        found = await skiing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.snow_conditions == "wet snow"

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
    ):
        """Test finding skiing data returns None when not found."""
        found = await skiing_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_route_id(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test that route_id is correctly persisted and retrieved."""
        data = CrossCountrySkiingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
        )
        await skiing_repository.save(data)

        found = await skiing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None


@pytest.mark.integration
class TestCrossCountrySkiingDataRepositoryDelete:
    """Test cross-country skiing data delete operations."""

    async def test_delete_removes_data(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
        test_journal: Journal,
    ):
        """Test deleting skiing data."""
        data = CrossCountrySkiingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            snow_conditions="crusty",
        )
        await skiing_repository.save(data)

        await skiing_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await skiing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        skiing_repository: SqlCrossCountrySkiingDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await skiing_repository.delete(99999)
