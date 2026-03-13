"""Integration tests for SqlFitnessDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, FitnessData, Journal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def fitness_data_repository(
    async_connection: AsyncConnection,
) -> SqlFitnessDataRepository:
    """Create a fitness data repository for testing."""
    return SqlFitnessDataRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def test_journal(
    journal_repository: SqlJournalRepository,
) -> Journal:
    """Create a test journal."""
    now = datetime.now(UTC)
    journal = Journal(
        user_id="test-user-123",
        title="Morning Run",
        content="Great run in the park",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=1),
        ),
    )
    return await journal_repository.save(journal)


def create_test_fitness_data(
    journal_id: int,
    heart_rate_avg: int | None = 145,
    heart_rate_max: int | None = 178,
    distance: int | None = 5000,
    elevation_gain: int | None = 100,
    elevation_loss: int | None = 90,
    duration: int | None = 1800,
    calories: int | None = 350,
    strava_activity_id: str | None = None,
) -> FitnessData:
    """Helper function to create test fitness data."""
    return FitnessData(
        journal_id=journal_id,
        heart_rate_avg=heart_rate_avg,
        heart_rate_max=heart_rate_max,
        distance=distance,
        elevation_gain=elevation_gain,
        elevation_loss=elevation_loss,
        duration=duration,
        calories=calories,
        strava_activity_id=strava_activity_id,
    )


@pytest.mark.integration
class TestFitnessDataRepositorySave:
    """Test fitness data save operations."""

    async def test_save_creates_new_fitness_data(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
        test_journal: Journal,
    ):
        """Test creating fitness data (adding FITNESS type to journal)."""
        fitness_data = create_test_fitness_data(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await fitness_data_repository.save(fitness_data)

        assert saved.journal_id == test_journal.id
        assert saved.heart_rate_avg == 145
        assert saved.heart_rate_max == 178
        assert saved.distance == 5000
        assert saved.elevation_gain == 100
        assert saved.elevation_loss == 90
        assert saved.duration == 1800
        assert saved.calories == 350
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
        test_journal: Journal,
    ):
        """Test creating fitness data with only required fields."""
        fitness_data = FitnessData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await fitness_data_repository.save(fitness_data)

        assert saved.journal_id == test_journal.id
        assert saved.heart_rate_avg is None
        assert saved.heart_rate_max is None
        assert saved.distance is None
        assert saved.elevation_gain is None
        assert saved.elevation_loss is None
        assert saved.duration is None
        assert saved.calories is None
        assert saved.strava_activity_id is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_strava_activity_id(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
        test_journal: Journal,
    ):
        """Test creating fitness data with Strava activity ID."""
        fitness_data = create_test_fitness_data(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            strava_activity_id="12345678",
        )

        saved = await fitness_data_repository.save(fitness_data)

        assert saved.strava_activity_id == "12345678"

    async def test_save_updates_existing_fitness_data(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing fitness data."""
        # Create initial fitness data
        fitness_data = create_test_fitness_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await fitness_data_repository.save(fitness_data)

        # Update with new values
        updated_data = FitnessData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            heart_rate_avg=150,
            heart_rate_max=185,
            distance=10000,
            elevation_gain=200,
            elevation_loss=180,
            duration=3600,
            calories=700,
        )
        saved = await fitness_data_repository.save(updated_data)

        assert saved.heart_rate_avg == 150
        assert saved.heart_rate_max == 185
        assert saved.distance == 10000
        assert saved.elevation_gain == 200
        assert saved.elevation_loss == 180
        assert saved.duration == 3600
        assert saved.calories == 700


@pytest.mark.integration
class TestFitnessDataRepositoryFind:
    """Test fitness data find operations."""

    async def test_find_by_journal_id_returns_fitness_data(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
        test_journal: Journal,
    ):
        """Test finding fitness data by journal ID."""
        # Create fitness data
        fitness_data = create_test_fitness_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await fitness_data_repository.save(fitness_data)

        # Find it
        found = await fitness_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.heart_rate_avg == 145
        assert found.distance == 5000

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
    ):
        """Test finding fitness data returns None when not found."""
        found = await fitness_data_repository.find_by_journal_id(99999)

        assert found is None


@pytest.mark.integration
class TestFitnessDataRepositoryDelete:
    """Test fitness data delete operations."""

    async def test_delete_removes_fitness_data(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
        test_journal: Journal,
    ):
        """Test deleting fitness data (removing FITNESS type from journal)."""
        # Create fitness data
        fitness_data = create_test_fitness_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await fitness_data_repository.save(fitness_data)

        # Delete it
        await fitness_data_repository.delete(test_journal.id)  # type: ignore[arg-type]

        # Verify it's gone
        found = await fitness_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_fitness_data_does_not_error(
        self,
        fitness_data_repository: SqlFitnessDataRepository,
    ):
        """Test deleting non-existent fitness data does not raise error."""
        # Should not raise an error
        await fitness_data_repository.delete(99999)
