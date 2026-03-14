"""Integration tests for SqlCalendarRepository."""

from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.journals import Calendar, CalendarNotFoundError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository


@pytest_asyncio.fixture
async def calendar_repository(
    async_connection: AsyncConnection,
) -> SqlCalendarRepository:
    """Create a calendar repository for testing."""
    return SqlCalendarRepository(async_connection)


def create_test_calendar(
    user_id: str = "test-user-123",
    name: str = "Test Calendar",
    color: str = "#FF5733",
    description: str | None = None,
    is_synced_to_google: bool = False,
    google_calendar_id: str | None = None,
) -> Calendar:
    """Helper function to create a test calendar."""
    return Calendar(
        user_id=user_id,
        name=name,
        color=color,
        description=description,
        is_synced_to_google=is_synced_to_google,
        google_calendar_id=google_calendar_id,
    )


@pytest.mark.integration
class TestCalendarRepositorySave:
    """Test calendar save operations."""

    async def test_save_creates_new_calendar(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test creating a new calendar."""
        calendar = create_test_calendar()

        saved = await calendar_repository.save(calendar)

        assert saved.id is not None
        assert saved.user_id == "test-user-123"
        assert saved.name == "Test Calendar"
        assert saved.color == "#FF5733"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_all_fields(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test creating a calendar with all optional fields."""
        calendar = create_test_calendar(
            description="Work events",
            is_synced_to_google=True,
            google_calendar_id="abc123@google.com",
        )

        saved = await calendar_repository.save(calendar)

        assert saved.description == "Work events"
        assert saved.is_synced_to_google is True
        assert saved.google_calendar_id == "abc123@google.com"

    async def test_save_updates_existing_calendar(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test updating an existing calendar."""
        calendar = create_test_calendar()
        saved = await calendar_repository.save(calendar)

        # Update the name
        saved.name = "Updated Calendar"
        updated = await calendar_repository.save(saved)

        assert updated.id == saved.id
        assert updated.name == "Updated Calendar"
        assert updated.updated_at is not None
        assert saved.updated_at is not None
        assert updated.updated_at >= saved.updated_at


@pytest.mark.integration
class TestCalendarRepositoryFindById:
    """Test calendar find by ID operations."""

    async def test_find_by_id_returns_calendar(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test finding a calendar by ID."""
        calendar = create_test_calendar()
        saved = await calendar_repository.save(calendar)

        found = await calendar_repository.find_by_id(saved.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.id == saved.id
        assert found.name == saved.name

    async def test_find_by_id_returns_none_for_missing(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test finding a non-existent calendar returns None."""
        found = await calendar_repository.find_by_id(uuid4())

        assert found is None


@pytest.mark.integration
class TestCalendarRepositoryDelete:
    """Test calendar delete operations."""

    async def test_delete_removes_calendar(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test deleting a calendar."""
        calendar = create_test_calendar()
        saved = await calendar_repository.save(calendar)

        await calendar_repository.delete(saved.id)  # type: ignore[arg-type]

        found = await calendar_repository.find_by_id(saved.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_raises_error(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test deleting a non-existent calendar raises error."""
        with pytest.raises(CalendarNotFoundError):
            await calendar_repository.delete(uuid4())


@pytest.mark.integration
class TestCalendarRepositoryQueries:
    """Test calendar query operations."""

    async def test_get_all_returns_user_calendars(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test getting all calendars for a user."""
        user1_c1 = create_test_calendar(user_id="user-1", name="User 1 Calendar 1")
        user1_c2 = create_test_calendar(user_id="user-1", name="User 1 Calendar 2")
        user2_c1 = create_test_calendar(user_id="user-2", name="User 2 Calendar 1")

        await calendar_repository.save(user1_c1)
        await calendar_repository.save(user1_c2)
        await calendar_repository.save(user2_c1)

        user1_calendars = await calendar_repository.get_all("user-1")

        assert len(user1_calendars) == 2
        assert all(c.user_id == "user-1" for c in user1_calendars)

    async def test_get_all_returns_ordered_by_name(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test calendars are returned ordered by name."""
        await calendar_repository.save(create_test_calendar(name="Zebra"))
        await calendar_repository.save(create_test_calendar(name="Alpha"))
        await calendar_repository.save(create_test_calendar(name="Middle"))

        calendars = await calendar_repository.get_all("test-user-123")

        assert calendars[0].name == "Alpha"
        assert calendars[1].name == "Middle"
        assert calendars[2].name == "Zebra"

    async def test_get_synced_calendars_returns_only_synced(
        self, calendar_repository: SqlCalendarRepository
    ):
        """Test getting only Google-synced calendars."""
        synced = create_test_calendar(
            name="Synced",
            is_synced_to_google=True,
            google_calendar_id="abc@google.com",
        )
        not_synced = create_test_calendar(name="Not Synced", is_synced_to_google=False)

        await calendar_repository.save(synced)
        await calendar_repository.save(not_synced)

        synced_calendars = await calendar_repository.get_synced_calendars(
            "test-user-123"
        )

        assert len(synced_calendars) == 1
        assert synced_calendars[0].name == "Synced"
        assert synced_calendars[0].is_synced_to_google is True
