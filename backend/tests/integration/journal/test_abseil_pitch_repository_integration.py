"""Integration tests for SqlAbseilPitchRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    EventDateRange,
    Journal,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def abseiling_repository(
    async_connection: AsyncConnection,
) -> SqlAbseilingDataRepository:
    """Create an abseiling data repository for testing."""
    return SqlAbseilingDataRepository(async_connection)


@pytest_asyncio.fixture
async def pitch_repository(
    async_connection: AsyncConnection,
) -> SqlAbseilPitchRepository:
    """Create an abseil pitch repository for testing."""
    return SqlAbseilPitchRepository(async_connection)


@pytest_asyncio.fixture
async def test_journal(
    journal_repository: SqlJournalRepository,
) -> Journal:
    """Create a test journal."""
    now = datetime.now(UTC)
    journal = Journal(
        user_id="test-user-123",
        title="Abseiling Trip - Blue Mountains",
        content="Multi-pitch abseil day",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=6),
        ),
    )
    return await journal_repository.save(journal)


@pytest_asyncio.fixture
async def test_abseiling_data(
    abseiling_repository: SqlAbseilingDataRepository,
    test_journal: Journal,
) -> AbseilingData:
    """Create test abseiling data (required parent for pitches)."""
    data = AbseilingData(
        journal_id=test_journal.id,  # type: ignore[arg-type]
        number_of_abseils=3,
        total_length=90,
    )
    return await abseiling_repository.save(data)


@pytest.mark.integration
class TestAbseilPitchRepositorySave:
    """Test abseil pitch save operations."""

    async def test_save_creates_new_pitch(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test creating a new abseil pitch."""
        pitch = AbseilPitch(
            journal_id=test_abseiling_data.journal_id,
            pitch_number=1,
            height=25,
            anchor_location="TR",
            anchor_type="double bolt",
            did_rescue=False,
            did_setup=True,
            notes="Watch out for loose rock",
        )

        saved = await pitch_repository.save(pitch)

        assert saved.id is not None
        assert saved.journal_id == test_abseiling_data.journal_id
        assert saved.pitch_number == 1
        assert saved.height == 25
        assert saved.anchor_location == "TR"
        assert saved.anchor_type == "double bolt"
        assert saved.did_rescue is False
        assert saved.did_setup is True
        assert saved.notes == "Watch out for loose rock"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_minimal_data(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test creating a pitch with only required fields."""
        pitch = AbseilPitch(
            journal_id=test_abseiling_data.journal_id,
            pitch_number=1,
        )

        saved = await pitch_repository.save(pitch)

        assert saved.id is not None
        assert saved.pitch_number == 1
        assert saved.height is None
        assert saved.anchor_location is None
        assert saved.anchor_type is None
        assert saved.did_rescue is None
        assert saved.did_setup is None
        assert saved.notes is None

    async def test_save_upsert_updates_existing_pitch(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test that saving a pitch with same journal_id and pitch_number updates it."""
        pitch = AbseilPitch(
            journal_id=test_abseiling_data.journal_id,
            pitch_number=1,
            height=20,
            anchor_type="single bolt",
            notes="Initial notes",
        )
        first_save = await pitch_repository.save(pitch)

        updated_pitch = AbseilPitch(
            journal_id=test_abseiling_data.journal_id,
            pitch_number=1,
            height=30,
            anchor_type="chains",
            did_rescue=True,
            notes="Updated notes",
        )
        second_save = await pitch_repository.save(updated_pitch)

        assert second_save.id == first_save.id
        assert second_save.height == 30
        assert second_save.anchor_type == "chains"
        assert second_save.did_rescue is True
        assert second_save.notes == "Updated notes"

    async def test_save_multiple_pitches_for_journal(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test saving multiple pitches for the same journal."""
        for i in range(1, 4):
            pitch = AbseilPitch(
                journal_id=test_abseiling_data.journal_id,
                pitch_number=i,
                height=20 + (i * 5),
            )
            await pitch_repository.save(pitch)

        pitches = await pitch_repository.find_by_journal_id(
            test_abseiling_data.journal_id
        )
        assert len(pitches) == 3


@pytest.mark.integration
class TestAbseilPitchRepositoryFind:
    """Test abseil pitch find operations."""

    async def test_find_by_journal_id_returns_ordered_by_pitch_number(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test that find_by_journal_id returns pitches ordered by pitch_number."""
        # Insert pitches out of order
        for pitch_num in [3, 1, 2]:
            pitch = AbseilPitch(
                journal_id=test_abseiling_data.journal_id,
                pitch_number=pitch_num,
                height=pitch_num * 10,
            )
            await pitch_repository.save(pitch)

        pitches = await pitch_repository.find_by_journal_id(
            test_abseiling_data.journal_id
        )

        assert len(pitches) == 3
        assert pitches[0].pitch_number == 1
        assert pitches[1].pitch_number == 2
        assert pitches[2].pitch_number == 3
        assert pitches[0].height == 10
        assert pitches[1].height == 20
        assert pitches[2].height == 30

    async def test_find_by_journal_id_returns_empty_when_none(
        self,
        pitch_repository: SqlAbseilPitchRepository,
    ):
        """Test that find_by_journal_id returns empty list when no pitches exist."""
        pitches = await pitch_repository.find_by_journal_id(99999)

        assert pitches == []


@pytest.mark.integration
class TestAbseilPitchRepositoryDelete:
    """Test abseil pitch delete operations."""

    async def test_delete_by_journal_id_removes_all_pitches(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test deleting all pitches for a journal."""
        for i in range(1, 4):
            pitch = AbseilPitch(
                journal_id=test_abseiling_data.journal_id,
                pitch_number=i,
            )
            await pitch_repository.save(pitch)

        await pitch_repository.delete_by_journal_id(test_abseiling_data.journal_id)

        pitches = await pitch_repository.find_by_journal_id(
            test_abseiling_data.journal_id
        )
        assert pitches == []

    async def test_delete_single_pitch(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test deleting a single pitch by ID."""
        pitch = AbseilPitch(
            journal_id=test_abseiling_data.journal_id,
            pitch_number=1,
            height=25,
        )
        saved = await pitch_repository.save(pitch)

        await pitch_repository.delete(saved.id)  # type: ignore[arg-type]

        pitches = await pitch_repository.find_by_journal_id(
            test_abseiling_data.journal_id
        )
        assert pitches == []

    async def test_cascade_delete_on_abseiling_data_removal(
        self,
        pitch_repository: SqlAbseilPitchRepository,
        abseiling_repository: SqlAbseilingDataRepository,
        test_abseiling_data: AbseilingData,
    ):
        """Test that deleting abseiling data cascades to remove all pitches."""
        for i in range(1, 3):
            pitch = AbseilPitch(
                journal_id=test_abseiling_data.journal_id,
                pitch_number=i,
            )
            await pitch_repository.save(pitch)

        # Delete the parent abseiling data
        await abseiling_repository.delete(test_abseiling_data.journal_id)

        # Pitches should be cascade-deleted
        pitches = await pitch_repository.find_by_journal_id(
            test_abseiling_data.journal_id
        )
        assert pitches == []
