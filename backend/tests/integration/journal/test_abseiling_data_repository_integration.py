"""Integration tests for SqlAbseilingDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.abseiling_data import AbseilingData
from app.core.journal.models.entities import Journal
from app.core.journal.models.value_objects import EventDateRange


@pytest_asyncio.fixture
async def abseiling_repository(
    async_connection: AsyncConnection,
) -> SqlAbseilingDataRepository:
    """Create an abseiling data repository for testing."""
    return SqlAbseilingDataRepository(async_connection)


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
        title="Abseiling Trip - Blue Mountains",
        content="Multi-pitch abseil in the Blue Mountains",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=6),
        ),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestAbseilingDataRepositorySave:
    """Test abseiling data save operations."""

    async def test_save_creates_new_abseiling_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test creating abseiling data (adding ABSEILING_TRIP type to journal)."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=5,
            total_length=120,
        )

        saved = await abseiling_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.number_of_abseils == 5
        assert saved.total_length == 120
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test creating abseiling data with only required fields."""
        data = AbseilingData(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await abseiling_repository.save(data)

        assert saved.journal_id == test_journal.id
        assert saved.number_of_abseils is None
        assert saved.total_length is None
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_updates_existing_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing abseiling data."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=3,
            total_length=80,
        )
        await abseiling_repository.save(data)

        updated_data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=7,
            total_length=200,
        )
        saved = await abseiling_repository.save(updated_data)

        assert saved.number_of_abseils == 7
        assert saved.total_length == 200


@pytest.mark.integration
class TestAbseilingDataRepositoryFind:
    """Test abseiling data find operations."""

    async def test_find_by_journal_id_returns_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test finding abseiling data by journal ID."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=5,
            total_length=120,
        )
        await abseiling_repository.save(data)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.number_of_abseils == 5
        assert found.total_length == 120

    async def test_find_by_journal_id_returns_none_when_not_found(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
    ):
        """Test finding abseiling data returns None when not found."""
        found = await abseiling_repository.find_by_journal_id(99999)

        assert found is None

    async def test_find_preserves_zero_values(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test that zero values are correctly persisted and retrieved."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=0,
            total_length=0,
        )
        await abseiling_repository.save(data)

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.number_of_abseils == 0
        assert found.total_length == 0


@pytest.mark.integration
class TestAbseilingDataRepositoryDelete:
    """Test abseiling data delete operations."""

    async def test_delete_removes_data(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
        test_journal: Journal,
    ):
        """Test deleting abseiling data."""
        data = AbseilingData(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            number_of_abseils=3,
        )
        await abseiling_repository.save(data)

        await abseiling_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await abseiling_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_data_does_not_error(
        self,
        abseiling_repository: SqlAbseilingDataRepository,
    ):
        """Test deleting non-existent data does not raise error."""
        await abseiling_repository.delete(99999)
