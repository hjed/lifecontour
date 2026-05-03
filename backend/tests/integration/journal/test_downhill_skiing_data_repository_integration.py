"""Integration tests for SqlDownhillSkiingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import DownhillSkiingData, EventDateRange, Journal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.downhill_skiing_data_repository import (
    SqlDownhillSkiingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def downhill_skiing_repository(
    async_connection: AsyncConnection,
) -> SqlDownhillSkiingDataRepository:
    """Create a downhill skiing data repository for testing."""
    return SqlDownhillSkiingDataRepository(async_connection)


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
        title="Test Skiing Trip",
        content="A nice ski",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=4),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestSqlDownhillSkiingDataRepository:
    """Integration tests for SqlDownhillSkiingDataRepository."""

    async def test_save_and_find_downhill_skiing_data(
        self,
        downhill_skiing_repository: SqlDownhillSkiingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving and retrieving downhill skiing data."""
        assert test_journal.id is not None
        # Arrange
        data = DownhillSkiingData(
            journal_id=test_journal.id,
        )

        # Act - Save
        saved = await downhill_skiing_repository.save(data)

        # Assert save result
        assert saved.journal_id == test_journal.id
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # Act - Find
        found = await downhill_skiing_repository.find_by_journal_id(test_journal.id)

        # Assert find result
        assert found is not None
        assert found.journal_id == test_journal.id

    async def test_update_downhill_skiing_data_upsert(
        self,
        downhill_skiing_repository: SqlDownhillSkiingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test updating existing downhill skiing data via upsert."""
        assert test_journal.id is not None
        # Arrange - Initial save
        initial_data = DownhillSkiingData(
            journal_id=test_journal.id,
        )
        await downhill_skiing_repository.save(initial_data)

        # Act - Update
        updated_data = DownhillSkiingData(
            journal_id=test_journal.id,
        )
        saved = await downhill_skiing_repository.save(updated_data)

        # Assert save result (mainly timestamps updated)
        assert saved.journal_id == test_journal.id

        # Assert database state
        found = await downhill_skiing_repository.find_by_journal_id(test_journal.id)
        assert found is not None

    async def test_delete_downhill_skiing_data(
        self,
        downhill_skiing_repository: SqlDownhillSkiingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test deleting downhill skiing data."""
        assert test_journal.id is not None
        # Arrange
        data = DownhillSkiingData(
            journal_id=test_journal.id,
        )
        await downhill_skiing_repository.save(data)

        # Verify it exists
        assert (
            await downhill_skiing_repository.find_by_journal_id(test_journal.id)
            is not None
        )

        # Act
        await downhill_skiing_repository.delete(test_journal.id)

        # Assert
        assert (
            await downhill_skiing_repository.find_by_journal_id(test_journal.id) is None
        )

    async def test_find_nonexistent_returns_none(
        self, downhill_skiing_repository: SqlDownhillSkiingDataRepository
    ) -> None:
        """Test finding data that doesn't exist returns None."""
        found = await downhill_skiing_repository.find_by_journal_id(999999)
        assert found is None
