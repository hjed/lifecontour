"""Integration tests for SqlCanoeingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import CanoeingData, EventDateRange, Journal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.canoeing_data_repository import (
    SqlCanoeingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def canoeing_repository(
    async_connection: AsyncConnection,
) -> SqlCanoeingDataRepository:
    """Create a canoeing data repository for testing."""
    return SqlCanoeingDataRepository(async_connection)


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
        title="Test Canoe Trip",
        content="A nice paddle on the river",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=4),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestSqlCanoeingDataRepository:
    """Integration tests for SqlCanoeingDataRepository."""

    async def test_save_and_find_canoeing_data(
        self,
        canoeing_repository: SqlCanoeingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving and retrieving canoeing data."""
        # Arrange
        data = CanoeingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="river",
        )

        # Act - Save
        saved = await canoeing_repository.save(data)

        # Assert save result
        assert saved.journal_id == test_journal.id
        assert saved.water_type == "river"

        # Act - Find
        found = await canoeing_repository.find_by_journal_id(test_journal.id)

        # Assert find result
        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.water_type == "river"

    async def test_update_canoeing_data(
        self,
        canoeing_repository: SqlCanoeingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test updating existing canoeing data via upsert."""
        # Arrange - Initial save
        initial_data = CanoeingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="river",
        )
        await canoeing_repository.save(initial_data)

        # Act - Update
        updated_data = CanoeingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="lake",
        )
        saved = await canoeing_repository.save(updated_data)

        # Assert save result
        assert saved.water_type == "lake"

        # Assert database state
        found = await canoeing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is not None
        assert found.water_type == "lake"

    async def test_delete_canoeing_data(
        self,
        canoeing_repository: SqlCanoeingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test deleting canoeing data."""
        # Arrange
        data = CanoeingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type="sea",
        )
        await canoeing_repository.save(data)

        # Verify it exists
        assert await canoeing_repository.find_by_journal_id(test_journal.id) is not None  # type: ignore[arg-type]

        # Act
        await canoeing_repository.delete(test_journal.id)  # type: ignore[arg-type]

        # Assert
        assert await canoeing_repository.find_by_journal_id(test_journal.id) is None  # type: ignore[arg-type]

    async def test_find_nonexistent_returns_none(
        self, canoeing_repository: SqlCanoeingDataRepository
    ) -> None:
        """Test finding data that doesn't exist returns None."""
        found = await canoeing_repository.find_by_journal_id(999999)
        assert found is None

    async def test_save_with_null_water_type(
        self,
        canoeing_repository: SqlCanoeingDataRepository,
        test_journal: Journal,
    ) -> None:
        """Test saving canoeing data with null water_type."""
        # Arrange
        data = CanoeingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            water_type=None,
        )

        # Act
        saved = await canoeing_repository.save(data)

        # Assert
        assert saved.water_type is None

        found = await canoeing_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is not None
        assert found.water_type is None
