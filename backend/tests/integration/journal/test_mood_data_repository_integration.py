"""Integration tests for SqlMoodDataRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.models.entities import Journal
from app.core.journal.models.mood_data import MoodData
from app.core.journal.models.value_objects import EventDateRange


@pytest_asyncio.fixture
async def mood_data_repository(
    async_connection: AsyncConnection,
) -> SqlMoodDataRepository:
    """Create a mood data repository for testing."""
    return SqlMoodDataRepository(async_connection)


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
        title="Mood Entry",
        content="How I'm feeling today",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=1),
        ),
    )
    return await journal_repository.save(journal)


def create_test_mood_data(
    journal_id: int,
    mood_value: int | None = 7,
    mood_label: str | None = "Content",
    energy_level: int | None = 6,
) -> MoodData:
    """Helper function to create test mood data."""
    return MoodData(
        journal_id=journal_id,
        mood_value=mood_value,
        mood_label=mood_label,
        energy_level=energy_level,
    )


@pytest.mark.integration
class TestMoodDataRepositorySave:
    """Test mood data save operations."""

    async def test_save_creates_new_mood_data(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test creating mood data (adding MOOD_RATING type to journal)."""
        mood_data = create_test_mood_data(journal_id=test_journal.id)  # type: ignore[arg-type]

        saved = await mood_data_repository.save(mood_data)

        assert saved.journal_id == test_journal.id
        assert saved.mood_value == 7
        assert saved.mood_label == "Content"
        assert saved.energy_level == 6
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_only_mood_value(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test creating mood data with only mood value."""
        mood_data = create_test_mood_data(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            mood_value=8,
            mood_label=None,
            energy_level=None,
        )

        saved = await mood_data_repository.save(mood_data)

        assert saved.mood_value == 8
        assert saved.mood_label is None
        assert saved.energy_level is None

    async def test_save_with_only_energy_level(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test creating mood data with only energy level."""
        mood_data = create_test_mood_data(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            mood_value=None,
            mood_label=None,
            energy_level=5,
        )

        saved = await mood_data_repository.save(mood_data)

        assert saved.mood_value is None
        assert saved.energy_level == 5

    async def test_save_updates_existing_mood_data(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test updating existing mood data."""
        mood_data = create_test_mood_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        saved = await mood_data_repository.save(mood_data)

        # Update the mood value
        saved.mood_value = 9
        saved.mood_label = "Excellent"
        updated = await mood_data_repository.save(saved)

        assert updated.journal_id == saved.journal_id
        assert updated.mood_value == 9
        assert updated.mood_label == "Excellent"


@pytest.mark.integration
class TestMoodDataRepositoryFindByJournalId:
    """Test mood data find operations."""

    async def test_find_by_journal_id_returns_mood_data(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test finding mood data by journal ID."""
        mood_data = create_test_mood_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await mood_data_repository.save(mood_data)

        found = await mood_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id
        assert found.mood_value == 7

    async def test_find_by_journal_id_returns_none_for_missing(
        self,
        mood_data_repository: SqlMoodDataRepository,
    ):
        """Test finding non-existent mood data returns None (journal has no MOOD_RATING type)."""
        found = await mood_data_repository.find_by_journal_id(99999)

        assert found is None


@pytest.mark.integration
class TestMoodDataRepositoryDelete:
    """Test mood data delete operations."""

    async def test_delete_removes_mood_data(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test deleting mood data (removing MOOD_RATING type from journal)."""
        mood_data = create_test_mood_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await mood_data_repository.save(mood_data)

        await mood_data_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await mood_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_does_not_raise(
        self,
        mood_data_repository: SqlMoodDataRepository,
    ):
        """Test deleting non-existent mood data doesn't raise error."""
        # This should not raise - delete is idempotent
        await mood_data_repository.delete(99999)


@pytest.mark.integration
class TestMoodDataTypeDetection:
    """Test type detection via mood data existence."""

    async def test_journal_has_mood_rating_type_when_data_exists(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test that a journal has MOOD_RATING type when mood data exists."""
        # Before adding mood data, find returns None
        found_before = await mood_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found_before is None

        # Add mood data
        mood_data = create_test_mood_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await mood_data_repository.save(mood_data)

        # Now the journal has MOOD_RATING type
        found_after = await mood_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found_after is not None

    async def test_journal_loses_mood_rating_type_when_data_deleted(
        self,
        mood_data_repository: SqlMoodDataRepository,
        test_journal: Journal,
    ):
        """Test that a journal loses MOOD_RATING type when mood data is deleted."""
        # Add mood data
        mood_data = create_test_mood_data(journal_id=test_journal.id)  # type: ignore[arg-type]
        await mood_data_repository.save(mood_data)

        # Journal has MOOD_RATING type
        found_before = await mood_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found_before is not None

        # Delete mood data
        await mood_data_repository.delete(test_journal.id)  # type: ignore[arg-type]

        # Journal no longer has MOOD_RATING type
        found_after = await mood_data_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found_after is None
