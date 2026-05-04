"""Integration tests for SqlOutdoorPlanningDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    OutdoorActivitySubtype,
    OutdoorPlanningData,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.outdoor_planning_data_repository import (
    SqlOutdoorPlanningDataRepository,
)


@pytest_asyncio.fixture
async def outdoor_planning_repository(
    async_connection: AsyncConnection,
) -> SqlOutdoorPlanningDataRepository:
    """Create an outdoor planning data repository for testing."""
    return SqlOutdoorPlanningDataRepository(async_connection)


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
        title="Planning Meeting",
        content="Planning the next trip",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=2),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestSqlOutdoorPlanningDataRepository:
    """Integration tests for SqlOutdoorPlanningDataRepository."""

    async def test_save_and_find(
        self,
        outdoor_planning_repository: SqlOutdoorPlanningDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving and finding outdoor planning data."""
        journal_id = test_journal.id
        assert journal_id is not None

        data = OutdoorPlanningData(
            journal_id=journal_id,
            topics="Discussed logistics for the upcoming trip.",
            activity_types=[
                OutdoorActivitySubtype.CANYONING.value,
                OutdoorActivitySubtype.BUSHWALKING.value,
            ],
        )

        # Save data
        saved_data = await outdoor_planning_repository.save(data)

        assert saved_data.journal_id == journal_id
        assert saved_data.topics == "Discussed logistics for the upcoming trip."
        assert saved_data.activity_types == ["canyoning", "bushwalking"]
        assert saved_data.created_at is not None
        assert saved_data.updated_at is not None

        # Find data
        found_data = await outdoor_planning_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.journal_id == journal_id
        assert found_data.topics == "Discussed logistics for the upcoming trip."
        assert found_data.activity_types == ["canyoning", "bushwalking"]

    async def test_save_updates_existing(
        self,
        outdoor_planning_repository: SqlOutdoorPlanningDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving updates existing outdoor planning data."""
        journal_id = test_journal.id
        assert journal_id is not None

        # Initial save
        data = OutdoorPlanningData(
            journal_id=journal_id,
            topics="Initial topics",
            activity_types=[OutdoorActivitySubtype.CLIMBING.value],
        )
        await outdoor_planning_repository.save(data)

        # Update data
        data.topics = "Updated topics"
        data.activity_types = [OutdoorActivitySubtype.CAVING.value]
        updated_data = await outdoor_planning_repository.save(data)

        assert updated_data.topics == "Updated topics"
        assert updated_data.activity_types == ["caving"]

        # Verify update persisted
        found_data = await outdoor_planning_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.topics == "Updated topics"
        assert found_data.activity_types == ["caving"]

    async def test_find_returns_none_if_not_found(
        self, outdoor_planning_repository: SqlOutdoorPlanningDataRepository
    ) -> None:
        """Test finding non-existent data returns None."""
        found_data = await outdoor_planning_repository.find_by_journal_id(99999)
        assert found_data is None

    async def test_delete(
        self,
        outdoor_planning_repository: SqlOutdoorPlanningDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test deleting outdoor planning data."""
        journal_id = test_journal.id
        assert journal_id is not None

        # Initial save
        data = OutdoorPlanningData(
            journal_id=journal_id,
            topics="Topics to delete",
            activity_types=[],
        )
        await outdoor_planning_repository.save(data)

        # Delete data
        await outdoor_planning_repository.delete(journal_id)

        # Verify deleted
        found_data = await outdoor_planning_repository.find_by_journal_id(journal_id)
        assert found_data is None

    async def test_cascade_delete_with_journal(
        self,
        outdoor_planning_repository: SqlOutdoorPlanningDataRepository,
        journal_repository: SqlJournalRepository,
        test_journal: Journal,
    ) -> None:
        """Test that deleting a journal cascade deletes outdoor planning data."""
        journal_id = test_journal.id
        assert journal_id is not None

        # Initial save
        data = OutdoorPlanningData(
            journal_id=journal_id,
            topics="Topics to cascade delete",
            activity_types=[],
        )
        await outdoor_planning_repository.save(data)

        # Delete journal
        await journal_repository.delete(journal_id)

        # Verify deleted
        found_data = await outdoor_planning_repository.find_by_journal_id(journal_id)
        assert found_data is None
