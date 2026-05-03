"""Integration tests for SqlSnorkellingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, Journal, SnorkellingData
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.snorkelling_data_repository import (
    SqlSnorkellingDataRepository,
)


@pytest_asyncio.fixture
async def snorkelling_repository(
    async_connection: AsyncConnection,
) -> SqlSnorkellingDataRepository:
    """Create a snorkelling data repository for testing."""
    return SqlSnorkellingDataRepository(async_connection)


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
        title="Test Snorkelling Trip",
        content="A nice swim on the reef",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=4),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestSqlSnorkellingDataRepository:
    """Integration tests for SqlSnorkellingDataRepository."""

    async def test_save_and_find_snorkelling_data(
        self,
        snorkelling_repository: SqlSnorkellingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving and retrieving snorkelling data."""
        assert test_journal.id is not None
        # Arrange
        data = SnorkellingData(
            journal_id=test_journal.id,
        )

        # Act - Save
        saved = await snorkelling_repository.save(data)

        # Assert save result
        assert saved.journal_id == test_journal.id
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # Act - Find
        found = await snorkelling_repository.find_by_journal_id(test_journal.id)

        # Assert find result
        assert found is not None
        assert found.journal_id == test_journal.id

    async def test_update_snorkelling_data_upsert(
        self,
        snorkelling_repository: SqlSnorkellingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test updating existing snorkelling data via upsert."""
        assert test_journal.id is not None
        # Arrange - Initial save
        initial_data = SnorkellingData(
            journal_id=test_journal.id,
        )
        await snorkelling_repository.save(initial_data)

        # Act - Update
        updated_data = SnorkellingData(
            journal_id=test_journal.id,
        )
        saved = await snorkelling_repository.save(updated_data)

        # Assert save result (mainly timestamps updated)
        assert saved.journal_id == test_journal.id

        # Assert database state
        found = await snorkelling_repository.find_by_journal_id(test_journal.id)
        assert found is not None

    async def test_delete_snorkelling_data(
        self,
        snorkelling_repository: SqlSnorkellingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test deleting snorkelling data."""
        assert test_journal.id is not None
        # Arrange
        data = SnorkellingData(
            journal_id=test_journal.id,
        )
        await snorkelling_repository.save(data)

        # Verify it exists
        assert (
            await snorkelling_repository.find_by_journal_id(test_journal.id) is not None
        )

        # Act
        await snorkelling_repository.delete(test_journal.id)

        # Assert
        assert await snorkelling_repository.find_by_journal_id(test_journal.id) is None

    async def test_find_nonexistent_returns_none(
        self, snorkelling_repository: SqlSnorkellingDataRepository
    ) -> None:
        """Test finding data that doesn't exist returns None."""
        found = await snorkelling_repository.find_by_journal_id(999999)
        assert found is None
