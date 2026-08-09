"""Integration tests for SqlCalendarInfoRepository."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import Calendar, CalendarInfo, EventDateRange, Journal
from core_shared.models.journals.event_state import EventState
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.statement_recorder import recorded_statements


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
    event_start_date: date | None = None,
    event_end_date: date | None = None,
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
        event_start_date=event_start_date,
        event_end_date=event_end_date,
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

    async def test_save_creates_external_event_link_for_legacy_event(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        async_connection: AsyncConnection,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Saving legacy CalendarInfo should seed the new per-calendar link table."""
        calendar_info = create_test_calendar_info(
            journal_id=test_journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
        )

        await calendar_info_repository.save(calendar_info)

        result = await async_connection.execute(
            text(
                """
                SELECT journal_id, calendar_id, external_event_id, external_version,
                       sync_capability, sync_status
                FROM journal_external_event_links
                WHERE journal_id = :journal_id
                """
            ),
            {"journal_id": test_journal.id},
        )
        row = result.fetchone()

        assert row is not None
        assert row.journal_id == test_journal.id
        assert row.calendar_id == test_calendar.id
        assert row.external_event_id is None
        assert row.external_version is None
        assert row.sync_capability == "outbound"
        assert row.sync_status == "pending"

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

    async def test_find_by_journal_id_supports_midnight_crossing_events(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        journal_repository: SqlJournalRepository,
        test_calendar: Calendar,
    ):
        """Test finding calendar info where end_time < start_time crosses midnight."""
        now = datetime.now(UTC)
        # Create a journal that starts at 11 PM and ends at 1 AM the next day
        start_dt = now.replace(hour=23, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(hours=2)

        journal = await journal_repository.save(
            Journal(
                user_id="test-user-123",
                title="Late Event",
                content="Event content",
                event_date_range=EventDateRange(
                    start=start_dt,
                    end=end_dt,
                ),
            )
        )

        calendar_info = create_test_calendar_info(
            journal_id=journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
            start_time=time(23, 0),
            end_time=time(1, 0),
            event_start_date=start_dt.date(),
            event_end_date=end_dt.date(),
        )

        await calendar_info_repository.save(calendar_info)

        # This should successfully map to CalendarInfo since `event_start_date` and `event_end_date` are correctly joined
        found = await calendar_info_repository.find_by_journal_id(journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == journal.id
        assert found.start_time == time(23, 0)
        assert found.end_time == time(1, 0)

    async def test_find_by_journal_id_preserves_local_dates_with_timezone(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        journal_repository: SqlJournalRepository,
        test_calendar: Calendar,
    ):
        """Test finding calendar info maps local dates using the timezone correctly across UTC boundaries."""
        # 23:00 UTC on day 1 = 10:00 Sydney on day 2
        start_dt = datetime(2023, 10, 25, 23, 0, tzinfo=UTC)
        end_dt = datetime(2023, 10, 26, 0, 0, tzinfo=UTC)

        journal = await journal_repository.save(
            Journal(
                user_id="test-user-123",
                title="Timezone Bound Event",
                content="Event content",
                event_date_range=EventDateRange(
                    start=start_dt,
                    end=end_dt,
                ),
            )
        )

        calendar_info = create_test_calendar_info(
            journal_id=journal.id,  # type: ignore[arg-type]
            calendar_id=test_calendar.id,
            start_time=time(10, 0),
            end_time=time(11, 0),
            # We seed it directly, but we want to assert the repository finds it correctly parsing local dates
            event_start_date=date(2023, 10, 26),
            event_end_date=date(2023, 10, 26),
        )
        calendar_info.timezone = "Australia/Sydney"

        await calendar_info_repository.save(calendar_info)

        found = await calendar_info_repository.find_by_journal_id(journal.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.journal_id == journal.id
        # The timezone was used to translate the UTC `event_date_range_start` (Oct 25) back to Local Date (Oct 26)
        assert found.event_start_date == date(2023, 10, 26)
        assert found.event_end_date == date(2023, 10, 26)


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

    async def test_delete_removes_external_event_links(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        async_connection: AsyncConnection,
        calendar_repository: SqlCalendarRepository,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Deleting legacy CalendarInfo should remove all per-calendar external links."""
        await calendar_info_repository.save(
            create_test_calendar_info(
                journal_id=test_journal.id,  # type: ignore[arg-type]
                calendar_id=test_calendar.id,
            )
        )
        second_calendar = await calendar_repository.save(
            Calendar(
                user_id="test-user-123",
                name="Second Calendar",
                color="#00AAFF",
            )
        )
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_external_event_links (
                    journal_id, calendar_id, external_event_id,
                    external_version, sync_capability, sync_status
                )
                VALUES (
                    :journal_id, :calendar_id, :external_event_id,
                    :external_version, :sync_capability, :sync_status
                )
                """
            ),
            {
                "journal_id": test_journal.id,
                "calendar_id": second_calendar.id,
                "external_event_id": "secondary-event-1",
                "external_version": "etag-2",
                "sync_capability": "bidirectional",
                "sync_status": "synced",
            },
        )

        await calendar_info_repository.delete(test_journal.id)  # type: ignore[arg-type]

        result = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM journal_external_event_links WHERE journal_id = :journal_id"
            ),
            {"journal_id": test_journal.id},
        )

        assert result.scalar_one() == 0

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

    async def test_get_by_calendar_id_includes_secondary_linked_calendar(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        async_connection: AsyncConnection,
        calendar_repository: SqlCalendarRepository,
        test_journal: Journal,
        test_calendar: Calendar,
    ):
        """Linked secondary calendars should still project the journal through legacy queries."""
        await calendar_info_repository.save(
            create_test_calendar_info(
                journal_id=test_journal.id,  # type: ignore[arg-type]
                calendar_id=test_calendar.id,
            )
        )
        second_calendar = await calendar_repository.save(
            Calendar(
                user_id="test-user-123",
                name="Secondary Calendar",
                color="#22AA22",
            )
        )
        assert second_calendar.id is not None

        await async_connection.execute(
            text(
                """
                INSERT INTO journal_external_event_links (
                    journal_id, calendar_id, external_event_id,
                    external_version, sync_capability, sync_status
                )
                VALUES (
                    :journal_id, :calendar_id, :external_event_id,
                    :external_version, :sync_capability, :sync_status
                )
                """
            ),
            {
                "journal_id": test_journal.id,
                "calendar_id": second_calendar.id,
                "external_event_id": "secondary-event-1",
                "external_version": "etag-2",
                "sync_capability": "bidirectional",
                "sync_status": "synced",
            },
        )

        events = await calendar_info_repository.get_by_calendar_id(second_calendar.id)

        assert len(events) == 1
        assert events[0].journal_id == test_journal.id
        assert events[0].calendar_id == second_calendar.id


@pytest.mark.integration
class TestCalendarInfoRepositoryFindCancelledJournalIds:
    """The batch cancellation read the tasks read model derives *lapsed* from.

    Batched rather than per-journal because the caller asks about a whole set at
    once — a task's three roles, or a journal's twenty tasks — and one
    ``find_by_journal_id`` per journal is exactly the N+1 the read model exists
    to avoid.
    """

    async def _event_journal(
        self,
        journal_repository: SqlJournalRepository,
        calendar_info_repository: SqlCalendarInfoRepository,
        calendar: Calendar,
        *,
        title: str,
        event_state: EventState,
    ) -> int:
        """A real event journal in ``event_state``, returning its id."""
        now = datetime.now(UTC)
        journal = await journal_repository.save(
            Journal(
                user_id="test-user-123",
                title=title,
                content="content",
                event_date_range=EventDateRange(
                    start=now, end=now + timedelta(hours=1)
                ),
            )
        )
        assert journal.id is not None
        assert calendar.id is not None
        await calendar_info_repository.save(
            CalendarInfo(
                journal_id=journal.id,
                calendar_id=calendar.id,
                event_state=event_state,
            )
        )
        return journal.id

    async def test_returns_only_the_cancelled_journals_from_a_mixed_set(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        journal_repository: SqlJournalRepository,
        test_calendar: Calendar,
    ):
        """Asked about four journals in four states, it names the cancelled one.

        The three survivors are the point: ``invited`` and ``tentative`` are not
        cancellations, and treating any non-confirmed state as one would lapse
        every task due in a meeting the user had not yet accepted.
        """
        journal_ids: dict[EventState, int] = {}
        for state in EventState:
            journal_ids[state] = await self._event_journal(
                journal_repository,
                calendar_info_repository,
                test_calendar,
                title=f"{state.value} event",
                event_state=state,
            )

        cancelled = await calendar_info_repository.find_cancelled_journal_ids(
            list(journal_ids.values())
        )

        assert cancelled == {journal_ids[EventState.CANCELLED]}

    async def test_a_journal_with_no_calendar_info_is_simply_absent(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        journal_repository: SqlJournalRepository,
        test_calendar: Calendar,
    ):
        """A plain note journal has no event state, so it is not cancelled.

        Cancellation is per-event-type data. A journal that was never an event
        must come back as *not cancelled* rather than as missing information the
        caller has to interpret.
        """
        now = datetime.now(UTC)
        note = await journal_repository.save(
            Journal(
                user_id="test-user-123",
                title="Just a note",
                content="content",
                event_date_range=EventDateRange(start=now, end=now),
            )
        )
        cancelled_id = await self._event_journal(
            journal_repository,
            calendar_info_repository,
            test_calendar,
            title="Called off",
            event_state=EventState.CANCELLED,
        )
        assert note.id is not None

        cancelled = await calendar_info_repository.find_cancelled_journal_ids(
            [note.id, cancelled_id]
        )

        assert cancelled == {cancelled_id}

    async def test_an_unknown_journal_id_is_absent_rather_than_an_error(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
    ):
        """Asking about an id that does not exist answers nothing, not a failure."""
        assert (
            await calendar_info_repository.find_cancelled_journal_ids([987654]) == set()
        )

    async def test_an_empty_request_asks_the_database_nothing(
        self,
        calendar_info_repository: SqlCalendarInfoRepository,
        async_connection: AsyncConnection,
    ):
        """No ids means no query.

        A task read model with no intermediate journals reaches this with an
        empty list on every single read, so the short-circuit is the common
        path rather than an edge case.
        """
        with recorded_statements(async_connection) as statements:
            found = await calendar_info_repository.find_cancelled_journal_ids([])

        assert found == set()
        assert statements == []
