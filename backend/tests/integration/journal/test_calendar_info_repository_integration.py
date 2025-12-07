"""Integration tests for SqlCalendarInfoRepository."""

from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.calendar import Calendar
from app.core.journal.models.calendar_info import CalendarInfo
from app.core.journal.models.entities import Journal
from app.core.journal.models.value_objects import EventDateRange


@pytest_asyncio.fixture
async def calendar_info_repository(
    async_connection: AsyncConnection,
) -> SqlCalendarInfoRepository:
    """Create a calendar info repository for testing."""
    return SqlCalendarInfoRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def calendar_repository(
    async_connection: AsyncConnection,
) -> SqlCalendarRepository:
    """Create a calendar repository for testing."""
    return SqlCalendarRepository(async_connection)


@pytest_asyncio.fixture
async def test_calendar(
    calendar_repository: SqlCalendarRepository,
) -> Calendar:
    """Create a test calendar."""
    calendar = Calendar(
        user_id="test-user-123",
        name="Test Calendar",
        color="#FF5733",
    )
    return await calendar_repository.save(calendar)


@pytest_asyncio.fixture
async def test_journal(
    journal_repository: SqlJournalRepository,
) -> Journal:
    """Create a test journal."""
    now = datetime.now(UTC)
    journal = Journal(
        user_id="test-user-123",
        title="Test Event",
        content="Event content",
        event_date_range=EventDateRange(
            start=now,
            end=now + timedelta(hours=2),
        ),
    )
    return await journal_repository.save(journal)


def create_test_calendar_info(
    journal_id: int,
    calendar_id,
    start_time: time | None = time(9, 0),
    end_time: time | None = time(17, 0),
    is_all_day: bool = False,
    location: str | None = None,
    sync_invitees: bool = False,
) -> CalendarInfo:
    """Helper function to create a test calendar info."""
    return CalendarInfo(
        journal_id=journal_id,
        calendar_id=calendar_id,
        start_time=start_time,
        end_time=end_time,
        is_all_day=is_all_day,
        location=location,
        sync_invitees=sync_invitees,
    )


@pytest.mark.integration
class TestCalendarInfoRepositorySave:
    """Test calendar info save operations."""

    async def test_save_creates_new_calendar_info(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Test creating calendar info (adding EVENT type to journal)."""
        calendar_info = create_test_calendar_info(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
        )

        saved = await calendar_info_repository.save(calendar_info)

        assert saved.journal_id == test_journal.id
        assert saved.calendar_id == test_calendar.id
        assert saved.start_time == time(9, 0)
        assert saved.end_time == time(17, 0)
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_all_day_event(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Test creating an all-day event."""
        calendar_info = create_test_calendar_info(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
            start_time=None,
            end_time=None,
            is_all_day=True,
        )

        saved = await calendar_info_repository.save(calendar_info)

        assert saved.is_all_day is True
        assert saved.start_time is None
        assert saved.end_time is None

    async def test_save_updates_existing_calendar_info(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Test updating existing calendar info."""
        calendar_info = create_test_calendar_info(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
        )
        saved = await calendar_info_repository.save(calendar_info)

        # Update the location
        saved.location = "Conference Room A"
        updated = await calendar_info_repository.save(saved)

        assert updated.journal_id == saved.journal_id
        assert updated.location == "Conference Room A"


@pytest.mark.integration
class TestCalendarInfoRepositoryFindByJournalId:
    """Test calendar info find operations."""

    async def test_find_by_journal_id_returns_calendar_info(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Test finding calendar info by journal ID."""
        calendar_info = create_test_calendar_info(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
        )
        await calendar_info_repository.save(calendar_info)

        found = await calendar_info_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == test_journal.id

    async def test_find_by_journal_id_returns_none_for_missing(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
    ):
        """Test finding non-existent calendar info returns None (journal has no EVENT type)."""
        found = await calendar_info_repository.find_by_journal_id(99999)

        assert found is None


@pytest.mark.integration
class TestCalendarInfoRepositoryDelete:
    """Test calendar info delete operations."""

    async def test_delete_removes_calendar_info(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Test deleting calendar info (removing EVENT type from journal)."""
        calendar_info = create_test_calendar_info(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
        )
        await calendar_info_repository.save(calendar_info)

        await calendar_info_repository.delete(test_journal.id)  # type: ignore[arg-type]

        found = await calendar_info_repository.find_by_journal_id(test_journal.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_does_not_raise(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
    ):
        """Test deleting non-existent calendar info doesn't raise error."""
        # This should not raise - delete is idempotent
        await calendar_info_repository.delete(99999)


@pytest.mark.integration
class TestCalendarInfoRepositoryGetByCalendarId:
    """Test getting calendar info by calendar ID."""

    async def test_get_by_calendar_id_returns_all_events(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        journal_repository: SqlJournalRepository,
        test_calendar: Calendar,
    ):
        """Test getting all events for a calendar."""
        now = datetime.now(UTC)

        # Create two journals with the same calendar
        journal1 = await journal_repository.save(
            Journal(
                user_id="test-user-123",
                title="Event 1",
                content="Content 1",
                event_date_range=EventDateRange(
                    start=now, end=now + timedelta(hours=1)
                ),
            )
        )
        journal2 = await journal_repository.save(
            Journal(
                user_id="test-user-123",
                title="Event 2",
                content="Content 2",
                event_date_range=EventDateRange(
                    start=now, end=now + timedelta(hours=2)
                ),
            )
        )

        # Add calendar info to both
        await calendar_info_repository.save(
            create_test_calendar_info(
                journal_id=journal1.id,  # type: ignore[arg-type]
                calendar_id=test_calendar.id,
            )
        )
        await calendar_info_repository.save(
            create_test_calendar_info(
                journal_id=journal2.id,  # type: ignore[arg-type]
                calendar_id=test_calendar.id,
            )
        )

        events = await calendar_info_repository.get_by_calendar_id(test_calendar.id)  # type: ignore[arg-type]

        assert len(events) == 2
        assert {e.journal_id for e in events} == {journal1.id, journal2.id}
