"""Integration tests for SqlCavingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import CavingData, EventDateRange, Journal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.caving_data_repository import (
    SqlCavingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def caving_repository(
    async_connection: AsyncConnection,
) -> SqlCavingDataRepository:
    """Create a caving data repository for testing."""
    return SqlCavingDataRepository(async_connection)


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
        title="Test Cave",
        content="A nice deep cave",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=8),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestSqlCavingDataRepository:
    """Integration tests for SqlCavingDataRepository."""

    async def test_save_and_find_caving_data(
        self,
        caving_repository: SqlCavingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving and retrieving caving data."""
        # Arrange
        data = CavingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            is_vertical=True,
            is_horizontal=False,
        )

        # Act - Save
        saved = await caving_repository.save(data)

        # Assert save result
        assert saved.journal_id == test_journal.id
        assert saved.is_vertical is True
        assert saved.is_horizontal is False

        # Act - Find
        found = await caving_repository.find_by_journal_id(test_journal.id)

        # Assert find result
        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.is_vertical is True
        assert found.is_horizontal is False

    async def test_update_caving_data(
        self,
        caving_repository: SqlCavingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test updating existing caving data via upsert."""
        # Arrange - Initial save
        initial_data = CavingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            is_vertical=True,
            is_horizontal=False,
        )
        await caving_repository.save(initial_data)

        # Act - Update
        updated_data = CavingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            is_vertical=False,
            is_horizontal=True,
        )
        saved = await caving_repository.save(updated_data)

        # Assert save result
        assert saved.is_vertical is False
        assert saved.is_horizontal is True

        # Assert database state
        found = await caving_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is not None
        assert found.is_vertical is False
        assert found.is_horizontal is True

    async def test_delete_caving_data(
        self,
        caving_repository: SqlCavingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test deleting caving data."""
        # Arrange
        data = CavingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            is_vertical=True,
            is_horizontal=False,
        )
        await caving_repository.save(data)

        # Verify it exists
        assert await caving_repository.find_by_journal_id(test_journal.id) is not None  # type: ignore[arg-type]

        # Act
        await caving_repository.delete(test_journal.id)  # type: ignore[arg-type]

        # Assert
        assert await caving_repository.find_by_journal_id(test_journal.id) is None  # type: ignore[arg-type]

    async def test_find_nonexistent_returns_none(
        self, caving_repository: SqlCavingDataRepository
    ) -> None:
        """Test finding data that doesn't exist returns None."""
        found = await caving_repository.find_by_journal_id(999999)
        assert found is None
