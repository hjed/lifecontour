"""Integration tests for SqlCanyoningDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import CanyoningData, EventDateRange, Journal
from core_shared.models.route import Route
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository


@pytest_asyncio.fixture
async def canyoning_repository(
    async_connection: AsyncConnection,
) -> SqlCanyoningDataRepository:
    """Create a canyoning data repository for testing."""
    return SqlCanyoningDataRepository(async_connection)


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
        title="Claustral Canyon",
        content="A full-day canyon in the Blue Mountains",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=8),
        ),
    )
    return await journal_repository.save(journal)


@pytest_asyncio.fixture
async def test_route(route_repository: SqlRouteRepository) -> Route:
    """Create a test route."""
    route = Route(
        user_id="test-user-123",
        name="Claustral Canyon Route",
        description="Classic Blue Mountains canyon",
    )
    return await route_repository.save(route)


@pytest.mark.integration
class TestCanyoningDataRepositorySave:
    """Test canyoning data save operations."""

    async def test_save_creates_new_canyoning_data(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
        test_journal: Journal,
    ):
        """Test creating canyoning data (adding CANYONING type to journal)."""
        data = CanyoningData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            french_grade="v3a2IV**",
            water_guage_name="Kanangra Creek",
            water_guage_level=45,
            is_vertical=True,
            is_night_canyon=False,
            is_white_water=True,
        )

        saved = await canyoning_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.french_grade == "v3a2IV**"
        assert saved.water_guage_name == "Kanangra Creek"
        assert saved.water_guage_level == 45
        assert saved.is_vertical is True
        assert saved.is_night_canyon is False
        assert saved.is_white_water is True
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
        test_journal: Journal,
    ):
        """Test creating canyoning data with only required fields."""
        data = CanyoningData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await canyoning_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.route_id is None
        assert saved.french_grade is None
        assert saved.water_guage_name is None
        assert saved.water_guage_level is None
        assert saved.is_vertical is None
        assert saved.is_night_canyon is None
        assert saved.is_white_water is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_route_id(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test creating canyoning data with a route reference."""
        data = CanyoningData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
            french_grade="v4a3II",
        )

        saved = await canyoning_repository.save(data)

        assert saved.route_id == test_route.id
        assert saved.french_grade == "v4a3II"

    async def test_save_updates_existing_data(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing canyoning data."""
        data = CanyoningData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            french_grade="v2a1",
            water_guage_level=30,
        )
        await canyoning_repository.save(data)

        updated_data = CanyoningData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            french_grade="v5a4VI***",
            water_guage_level=80,
            is_night_canyon=True,
        )
        saved = await canyoning_repository.save(updated_data)

        assert saved.french_grade == "v5a4VI***"
        assert saved.water_guage_level == 80
        assert saved.is_night_canyon is True


@pytest.mark.integration
class TestCanyoningDataRepositoryFind:
    """Test canyoning data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
        test_journal: Journal,
    ):
        """Test finding canyoning data by journal ID."""
        data = CanyoningData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            french_grade="v3a2IV**",
            water_guage_name="Claustral Creek",
            is_vertical=True,
        )
        await canyoning_repository.save(data)

        found = await canyoning_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.french_grade == "v3a2IV**"
        assert found.water_guage_name == "Claustral Creek"
        assert found.is_vertical is True

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
    ):
        """Test finding canyoning data returns None when not found."""
        found = await canyoning_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_route_id(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
        test_journal: Journal,
        test_route: Route,
    ):
        """Test that route_id is correctly persisted and retrieved."""
        data = CanyoningData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            route_id=test_route.id,
        )
        await canyoning_repository.save(data)

        found = await canyoning_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.route_id == test_route.id


@pytest.mark.integration
class TestCanyoningDataRepositoryDelete:
    """Test canyoning data delete operations."""

    async def test_delete_removes_data(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
        test_journal: Journal,
    ):
        """Test deleting canyoning data."""
        data = CanyoningData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            french_grade="v2a1",
        )
        await canyoning_repository.save(data)

        await canyoning_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await canyoning_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        canyoning_repository: SqlCanyoningDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await canyoning_repository.delete(99999)
