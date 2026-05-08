"""Integration tests for SqlOutdoorTrainingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    OutdoorActivitySubtype,
    OutdoorTrainingData,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.outdoor_training_data_repository import (
    SqlOutdoorTrainingDataRepository,
)


@pytest_asyncio.fixture
async def outdoor_training_repository(
    async_connection: AsyncConnection,
) -> SqlOutdoorTrainingDataRepository:
    """Create an outdoor training data repository for testing."""
    return SqlOutdoorTrainingDataRepository(async_connection)


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
        title="Training Session",
        content="Working on skills",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=2),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestSqlOutdoorTrainingDataRepository:
    """Integration tests for SqlOutdoorTrainingDataRepository."""

    async def test_save_and_find(
        self,
        outdoor_training_repository: SqlOutdoorTrainingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving and finding outdoor training data."""
        journal_id = test_journal.id
        assert journal_id is not None

        data = OutdoorTrainingData(
            journal_id=journal_id,
            focus_areas=[
                OutdoorActivitySubtype.CANYONING.value,
                OutdoorActivitySubtype.BUSHWALKING.value,
            ],
        )

        # Save data
        saved_data = await outdoor_training_repository.save(data)

        assert saved_data.journal_id == journal_id
        assert saved_data.focus_areas == ["canyoning", "bushwalking"]
        assert saved_data.created_at is not None
        assert saved_data.updated_at is not None

        # Find data
        found_data = await outdoor_training_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.journal_id == journal_id
        assert found_data.focus_areas == ["canyoning", "bushwalking"]

    async def test_save_updates_existing(
        self,
        outdoor_training_repository: SqlOutdoorTrainingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving updates existing outdoor training data."""
        journal_id = test_journal.id
        assert journal_id is not None

        # Initial save
        data = OutdoorTrainingData(
            journal_id=journal_id,
            focus_areas=[OutdoorActivitySubtype.CLIMBING.value],
        )
        await outdoor_training_repository.save(data)

        # Update data
        data.focus_areas = [OutdoorActivitySubtype.CAVING.value, "Navigation"]
        updated_data = await outdoor_training_repository.save(data)

        assert updated_data.focus_areas == ["caving", "Navigation"]

        # Verify update persisted
        found_data = await outdoor_training_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.focus_areas == ["caving", "Navigation"]

    async def test_find_returns_none_if_not_found(
        self, outdoor_training_repository: SqlOutdoorTrainingDataRepository
    ) -> None:
        """Test finding non-existent data returns None."""
        found_data = await outdoor_training_repository.find_by_journal_id(99999)
        assert found_data is None

    async def test_delete(
        self,
        outdoor_training_repository: SqlOutdoorTrainingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test deleting outdoor training data."""
        journal_id = test_journal.id
        assert journal_id is not None

        # Initial save
        data = OutdoorTrainingData(
            journal_id=journal_id,
            focus_areas=[],
        )
        await outdoor_training_repository.save(data)

        # Delete data
        await outdoor_training_repository.delete(journal_id)

        # Verify deleted
        found_data = await outdoor_training_repository.find_by_journal_id(journal_id)
        assert found_data is None

    async def test_cascade_delete_with_journal(
        self,
        outdoor_training_repository: SqlOutdoorTrainingDataRepository,
        journal_repository: SqlJournalRepository,
        test_journal: Journal,
    ) -> None:
        """Test that deleting a journal cascade deletes outdoor training data."""
        journal_id = test_journal.id
        assert journal_id is not None

        # Initial save
        data = OutdoorTrainingData(
            journal_id=journal_id,
            focus_areas=[],
        )
        await outdoor_training_repository.save(data)

        # Delete journal
        await journal_repository.delete(journal_id)

        # Verify deleted
        found_data = await outdoor_training_repository.find_by_journal_id(journal_id)
        assert found_data is None
