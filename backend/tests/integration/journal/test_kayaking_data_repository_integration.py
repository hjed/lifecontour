"""Integration tests for SqlKayakingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.kayaking_data_repository import (
    SqlKayakingDataRepository,
)
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.models.entities import Journal
from app.core.journal.models.kayaking_data import KayakingData
from app.core.journal.models.value_objects import EventDateRange


@pytest_asyncio.fixture
async def kayaking_repository(
    async_connection: AsyncConnection,
) -> SqlKayakingDataRepository:
    """Create a kayaking data repository for testing."""
    return SqlKayakingDataRepository(async_connection)


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
        title="Kayaking on the Murray",
        content="Kayaking trip on the Murray River",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=3),
        ),
    )
    return await journal_repository.save(journal)


@pytest_asyncio.fixture
async def test_route(route_repository: SqlRouteRepository) -> Route:
    """Create a test route."""
    route = Route(
        user_id="test-user-123",
        name="Murray River Paddle",
        description="Paddle route along the Murray River",
    )
    return await route_repository.save(route)


@pytest.mark.integration
class TestKayakingDataRepositorySave:
    """Test kayaking data save operations."""

    async def test_save_creates_new_kayaking_data(
        self,
        kayaking_repository: SqlKayakingDataRepository,
        test_journal: Journal,
    ):
        """Test creating kayaking data (adding KAYAKING type to journal)."""
        data = KayakingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="river",
        )

        saved = await kayaking_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.water_type == "river"
        assert saved.route_id is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        kayaking_repository: SqlKayakingDataRepository,
        test_journal: Journal,
    ):
        """Test creating kayaking data with only required fields."""
        data = KayakingData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await kayaking_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.route_id is None
        assert saved.water_type is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_route_id(
        self,
        kayaking_repository: SqlKayakingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test creating kayaking data with a route reference."""
        data = KayakingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
            water_type="lake",
        )

        saved = await kayaking_repository.save(data)

        assert saved.route_id == test_route.id
        assert saved.water_type == "lake"

    async def test_save_updates_existing_data(
        self,
        kayaking_repository: SqlKayakingDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing kayaking data."""
        data = KayakingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="river",
        )
        await kayaking_repository.save(data)

        updated_data = KayakingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="sea",
        )
        saved = await kayaking_repository.save(updated_data)

        assert saved.water_type == "sea"


@pytest.mark.integration
class TestKayakingDataRepositoryFind:
    """Test kayaking data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        kayaking_repository: SqlKayakingDataRepository,
        test_journal: Journal,
    ):
        """Test finding kayaking data by journal ID."""
        data = KayakingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="river",
        )
        await kayaking_repository.save(data)

        found = await kayaking_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.water_type == "river"

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        kayaking_repository: SqlKayakingDataRepository,
    ):
        """Test finding kayaking data returns None when not found."""
        found = await kayaking_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_route_id(
        self,
        kayaking_repository: SqlKayakingDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test that route_id is correctly persisted and retrieved."""
        data = KayakingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
        )
        await kayaking_repository.save(data)

        found = await kayaking_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.route_id == test_route.id


@pytest.mark.integration
class TestKayakingDataRepositoryDelete:
    """Test kayaking data delete operations."""

    async def test_delete_removes_data(
        self,
        kayaking_repository: SqlKayakingDataRepository,
        test_journal: Journal,
    ):
        """Test deleting kayaking data."""
        data = KayakingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="sea",
        )
        await kayaking_repository.save(data)

        await kayaking_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await kayaking_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        kayaking_repository: SqlKayakingDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await kayaking_repository.delete(99999)
