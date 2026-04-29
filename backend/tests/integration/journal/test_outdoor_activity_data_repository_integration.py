"""Integration tests for SqlOutdoorActivityDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, Journal, OutdoorActivityData
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)


@pytest_asyncio.fixture
async def outdoor_activity_repository(
    async_connection: AsyncConnection,
) -> SqlOutdoorActivityDataRepository:
    """Create an outdoor activity data repository for testing."""
    return SqlOutdoorActivityDataRepository(async_connection)


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
        title="Mountain Hike",
        content="Great day in the mountains",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=4),
        ),
    )
    return await journal_repository.save(journal)


def create_test_outdoor_activity_data(
    journal_id: int,
    weather_conditions: str | None = "Sunny, 22°C",
    role: str | None = "leader",
    in_leadership_role: bool | None = True,
    participant_notes: str | None = "Group of 5 hikers",
) -> OutdoorActivityData:
    """Helper to create test outdoor activity data."""
    return OutdoorActivityData(
        journal_id=journal_id,
        weather_conditions=weather_conditions,
        role=role,
        in_leadership_role=in_leadership_role,
        participant_notes=participant_notes,
    )


@pytest.mark.integration
class TestOutdoorActivityDataRepositorySave:
    """Test outdoor activity data save operations."""

    async def test_save_creates_new_outdoor_activity_data(
        self,
        outdoor_activity_repository: SqlOutdoorActivityDataRepository,
        test_journal: Journal,
    ):
        """Test creating outdoor activity data (adding OUTDOOR_ACTIVITY type)."""
        data = create_test_outdoor_activity_data(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await outdoor_activity_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.weather_conditions == "Sunny, 22°C"
        assert saved.role == "leader"
        assert saved.in_leadership_role is True
        assert saved.participant_notes == "Group of 5 hikers"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        outdoor_activity_repository: SqlOutdoorActivityDataRepository,
        test_journal: Journal,
    ):
        """Test creating outdoor activity data with only required fields."""
        data = OutdoorActivityData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await outdoor_activity_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.weather_conditions is None
        assert saved.role is None
        assert saved.in_leadership_role is None
        assert saved.participant_notes is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_updates_existing_data(
        self,
        outdoor_activity_repository: SqlOutdoorActivityDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing outdoor activity data."""
        data = create_test_outdoor_activity_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await outdoor_activity_repository.save(data)

        updated_data = OutdoorActivityData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            weather_conditions="Cloudy, 15°C",
            role="participant",
            in_leadership_role=False,
            participant_notes="Solo camping trip",
        )
        saved = await outdoor_activity_repository.save(updated_data)

        assert saved.weather_conditions == "Cloudy, 15°C"
        assert saved.role == "participant"
        assert saved.in_leadership_role is False
        assert saved.participant_notes == "Solo camping trip"


@pytest.mark.integration
class TestOutdoorActivityDataRepositoryFind:
    """Test outdoor activity data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        outdoor_activity_repository: SqlOutdoorActivityDataRepository,
        test_journal: Journal,
    ):
        """Test finding outdoor activity data by journal ID."""
        data = create_test_outdoor_activity_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await outdoor_activity_repository.save(data)

        found = await outdoor_activity_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.in_leadership_role is True

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        outdoor_activity_repository: SqlOutdoorActivityDataRepository,
    ):
        """Test finding outdoor activity data returns None when not found."""
        found = await outdoor_activity_repository.find_by_journal_id(99999)

        assert found is None


@pytest.mark.integration
class TestOutdoorActivityDataRepositoryDelete:
    """Test outdoor activity data delete operations."""

    async def test_delete_removes_data(
        self,
        outdoor_activity_repository: SqlOutdoorActivityDataRepository,
        test_journal: Journal,
    ):
        """Test deleting outdoor activity data."""
        data = create_test_outdoor_activity_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await outdoor_activity_repository.save(data)

        await outdoor_activity_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await outdoor_activity_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        outdoor_activity_repository: SqlOutdoorActivityDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await outdoor_activity_repository.delete(99999)
