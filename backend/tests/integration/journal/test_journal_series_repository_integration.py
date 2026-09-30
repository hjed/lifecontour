"""Integration tests for SqlJournalSeriesRepository."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from core_shared.models.journals import Calendar, EventDateRange, Journal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.journal.models.journal_series import JournalSeries

USER_ID = "series-test-user"
OTHER_USER_ID = "series-other-user"


def _sid(series: JournalSeries) -> uuid.UUID:
    assert series.id is not None
    return series.id


def _cid(calendar: Calendar) -> uuid.UUID:
    assert calendar.id is not None
    return calendar.id


@pytest_asyncio.fixture
async def series_repository(
    async_connection: AsyncConnection,
) -> SqlJournalSeriesRepository:
    return SqlJournalSeriesRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(async_connection: AsyncConnection) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def calendar_repository(
    async_connection: AsyncConnection,
) -> SqlCalendarRepository:
    return SqlCalendarRepository(async_connection)


async def _create_journal(
    journal_repository: SqlJournalRepository,
    title: str = "Series member journal",
    user_id: str = USER_ID,
) -> Journal:
    journal = Journal(
        user_id=user_id,
        title=title,
        content="",
        event_date_range=EventDateRange(
            start=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
            end=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        ),
    )
    return await journal_repository.save(journal)


async def _create_calendar(
    calendar_repository: SqlCalendarRepository, user_id: str = USER_ID
) -> Calendar:
    return await calendar_repository.save(
        Calendar(user_id=user_id, name=f"Cal {uuid.uuid4().hex[:8]}", color="#336699")
    )


async def _holds_recurrence_lock(
    connection: AsyncConnection, calendar_id: uuid.UUID, recurring_event_id: str
) -> bool:
    """Whether this transaction holds the advisory lock for a recurrence key."""
    result = await connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_locks
                WHERE locktype = 'advisory' AND pid = pg_backend_pid()
                  AND objsubid = 1
                  AND ((classid::bigint << 32) | objid::bigint)
                      = hashtextextended(:key, 0)
            )
            """
        ),
        {"key": f"journal_series_recurrence:{calendar_id}:{recurring_event_id}"},
    )
    return bool(result.scalar())


@pytest.mark.integration
class TestJournalSeriesSave:
    async def test_save_creates_series_with_generated_id(
        self, series_repository: SqlJournalSeriesRepository
    ) -> None:
        series = JournalSeries(user_id=USER_ID, name="Physio appointments")

        saved = await series_repository.save(series)

        assert saved.id is not None
        assert saved.created_at is not None
        assert saved.updated_at is not None
        assert saved.name == "Physio appointments"

    async def test_save_updates_existing_series(
        self, series_repository: SqlJournalSeriesRepository
    ) -> None:
        saved = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Original")
        )
        saved.name = "Renamed"
        saved.description = "with description"

        updated = await series_repository.save(saved)

        fetched = await series_repository.find_by_id(_sid(updated), USER_ID)
        assert fetched is not None
        assert fetched.name == "Renamed"
        assert fetched.description == "with description"


@pytest.mark.integration
class TestJournalSeriesFind:
    async def test_find_by_id_is_user_scoped(
        self, series_repository: SqlJournalSeriesRepository
    ) -> None:
        saved = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Mine")
        )

        assert await series_repository.find_by_id(_sid(saved), USER_ID) is not None
        assert await series_repository.find_by_id(_sid(saved), OTHER_USER_ID) is None

    async def test_find_all_returns_only_user_series_ordered_by_name(
        self, series_repository: SqlJournalSeriesRepository
    ) -> None:
        await series_repository.save(JournalSeries(user_id=USER_ID, name="Zebra"))
        await series_repository.save(JournalSeries(user_id=USER_ID, name="Alpha"))
        await series_repository.save(
            JournalSeries(user_id=OTHER_USER_ID, name="Not mine")
        )

        result = await series_repository.find_all(USER_ID)

        assert [s.name for s in result] == ["Alpha", "Zebra"]


@pytest.mark.integration
class TestGetOrCreateByRecurrence:
    async def test_creates_then_returns_same_series(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)

        first = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="master123",
            name="Weekly standup",
        )
        second = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="master123",
            name="A different name that must not create a new series",
        )

        assert first.id == second.id
        assert second.name == "Weekly standup"
        assert first.auto_created is True

    async def test_keyed_by_calendar_and_master_id(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar_a = await _create_calendar(calendar_repository)
        calendar_b = await _create_calendar(calendar_repository)

        same_master_other_calendar = (
            await series_repository.get_or_create_by_recurrence(
                user_id=USER_ID,
                calendar_id=_cid(calendar_a),
                recurring_event_id="master123",
                name="Series A",
            )
        )
        other_calendar = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar_b),
            recurring_event_id="master123",
            name="Series B",
        )
        other_master = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar_a),
            recurring_event_id="master456",
            name="Series C",
        )

        ids = {
            same_master_other_calendar.id,
            other_calendar.id,
            other_master.id,
        }
        assert len(ids) == 3


@pytest.mark.integration
class TestSeriesMembership:
    async def test_add_member_is_idempotent(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        series = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Series")
        )
        journal = await _create_journal(journal_repository)
        assert journal.id is not None

        await series_repository.add_member(_sid(series), journal.id)
        await series_repository.add_member(_sid(series), journal.id)

        assert await series_repository.get_member_journal_ids(_sid(series)) == [
            journal.id
        ]

    async def test_remove_member_is_idempotent(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        series = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Series")
        )
        journal = await _create_journal(journal_repository)
        assert journal.id is not None
        await series_repository.add_member(_sid(series), journal.id)

        await series_repository.remove_member(_sid(series), journal.id)
        await series_repository.remove_member(_sid(series), journal.id)

        assert await series_repository.get_member_journal_ids(_sid(series)) == []

    async def test_get_series_for_journal_returns_all_memberships(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        series_a = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Auto series")
        )
        series_b = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Manual series")
        )
        journal = await _create_journal(journal_repository)
        assert journal.id is not None
        await series_repository.add_member(_sid(series_a), journal.id)
        await series_repository.add_member(_sid(series_b), journal.id)

        result = await series_repository.get_series_for_journal(journal.id, USER_ID)

        assert {s.name for s in result} == {"Auto series", "Manual series"}

    async def test_get_series_for_journal_is_user_scoped(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        series = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Series")
        )
        journal = await _create_journal(journal_repository)
        assert journal.id is not None
        await series_repository.add_member(_sid(series), journal.id)

        assert (
            await series_repository.get_series_for_journal(journal.id, OTHER_USER_ID)
            == []
        )

    async def test_get_series_names_for_journal_ids_bulk(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        series = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Physio")
        )
        member = await _create_journal(journal_repository, title="Member")
        non_member = await _create_journal(journal_repository, title="Non member")
        assert member.id is not None and non_member.id is not None
        await series_repository.add_member(_sid(series), member.id)

        result = await series_repository.get_series_names_for_journal_ids(
            [member.id, non_member.id], USER_ID
        )

        assert result == {member.id: ["Physio"]}


@pytest.mark.integration
class TestSeriesCascades:
    async def test_member_rows_cascade_on_journal_delete(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ) -> None:
        series = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Series")
        )
        journal = await _create_journal(journal_repository)
        assert journal.id is not None
        await series_repository.add_member(_sid(series), journal.id)

        await journal_repository.delete(journal.id)

        assert await series_repository.get_member_journal_ids(_sid(series)) == []
        # The series itself survives.
        assert await series_repository.find_by_id(_sid(series), USER_ID) is not None

    async def test_delete_series_removes_memberships_but_not_journals(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ) -> None:
        series = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Series")
        )
        journal = await _create_journal(journal_repository)
        assert journal.id is not None
        await series_repository.add_member(_sid(series), journal.id)

        await series_repository.delete(_sid(series), USER_ID)

        assert await series_repository.find_by_id(_sid(series), USER_ID) is None
        assert await journal_repository.find_by_id(journal.id) is not None
        membership_count = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM journal_series_members"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal.id},
        )
        assert membership_count.scalar() == 0


@pytest.mark.integration
class TestMoveMembers:
    async def test_moves_members_and_dedupes_shared_journals(
        self,
        series_repository: SqlJournalSeriesRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        source = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Source")
        )
        destination = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Destination")
        )
        only_source = await _create_journal(journal_repository, title="Only source")
        shared = await _create_journal(journal_repository, title="Shared")
        assert only_source.id is not None and shared.id is not None
        await series_repository.add_member(_sid(source), only_source.id)
        await series_repository.add_member(_sid(source), shared.id)
        await series_repository.add_member(_sid(destination), shared.id)

        await series_repository.move_members(_sid(source), _sid(destination))

        assert await series_repository.get_member_journal_ids(_sid(source)) == []
        assert set(
            await series_repository.get_member_journal_ids(_sid(destination))
        ) == {only_source.id, shared.id}


@pytest.mark.integration
class TestRecurrenceAliases:
    async def test_aliased_recurrence_resolves_to_the_absorbing_series(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)
        source = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="source-master",
            name="Source",
        )
        destination = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Destination")
        )

        await series_repository.alias_recurrences(source, _sid(destination))
        await series_repository.delete(_sid(source), USER_ID)
        resolved = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="source-master",
            name="Must not re-create the source",
        )

        assert resolved.id == destination.id
        assert [s.name for s in await series_repository.find_all(USER_ID)] == [
            "Destination"
        ]

    async def test_existing_aliases_follow_a_chained_merge(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)
        first = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="first-master",
            name="First",
        )
        second = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="second-master",
            name="Second",
        )
        third = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Third")
        )

        await series_repository.alias_recurrences(first, _sid(second))
        await series_repository.delete(_sid(first), USER_ID)
        await series_repository.alias_recurrences(second, _sid(third))
        await series_repository.delete(_sid(second), USER_ID)

        for master in ("first-master", "second-master"):
            resolved = await series_repository.get_or_create_by_recurrence(
                user_id=USER_ID,
                calendar_id=_cid(calendar),
                recurring_event_id=master,
                name="Must not be created",
            )
            assert resolved.id == third.id

    async def test_holds_every_recurrence_key_it_repoints(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
        async_connection: AsyncConnection,
    ) -> None:
        # A sync for any key the absorbed series answers for (its own or one
        # it inherited) must wait for the merge: otherwise it can add a journal
        # to the absorbed series after its members moved, and deleting the
        # series drops that membership.
        # Seeded directly, as an earlier merge left it: ``save`` and a plain
        # INSERT take no advisory locks, and a transaction-level lock cannot be
        # released mid-test, so only the call under test may hold any.
        calendar = await _create_calendar(calendar_repository)
        second = await series_repository.save(
            JournalSeries(
                user_id=USER_ID,
                name="Second",
                calendar_id=_cid(calendar),
                recurring_event_id="second-master",
            )
        )
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_series_recurrence_aliases
                    (calendar_id, recurring_event_id, series_id, user_id)
                VALUES (:calendar_id, 'first-master', :series_id, :user_id)
                """
            ),
            {
                "calendar_id": _cid(calendar),
                "series_id": _sid(second),
                "user_id": USER_ID,
            },
        )
        third = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Third")
        )

        await series_repository.alias_recurrences(second, _sid(third))

        for master in ("first-master", "second-master"):
            assert await _holds_recurrence_lock(
                async_connection, _cid(calendar), master
            ), master

    async def test_aliases_cascade_when_the_absorbing_series_is_deleted(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)
        source = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="source-master",
            name="Source",
        )
        destination = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Destination")
        )
        await series_repository.alias_recurrences(source, _sid(destination))
        await series_repository.delete(_sid(source), USER_ID)

        await series_repository.delete(_sid(destination), USER_ID)
        recreated = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="source-master",
            name="Recreated",
        )

        assert recreated.id not in {source.id, destination.id}
        assert recreated.name == "Recreated"

    async def test_manual_series_adds_no_alias(
        self,
        series_repository: SqlJournalSeriesRepository,
        async_connection: AsyncConnection,
    ) -> None:
        source = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Manual source")
        )
        destination = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Destination")
        )

        await series_repository.alias_recurrences(source, _sid(destination))

        count = await async_connection.execute(
            text("SELECT COUNT(*) FROM journal_series_recurrence_aliases")
        )
        assert count.scalar() == 0

    async def test_alias_is_not_visible_to_another_user(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)
        source = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="source-master",
            name="Source",
        )
        destination = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Destination")
        )
        await series_repository.alias_recurrences(source, _sid(destination))
        await series_repository.delete(_sid(source), USER_ID)

        other = await series_repository.get_or_create_by_recurrence(
            user_id=OTHER_USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="source-master",
            name="Other user's series",
        )

        assert other.id != destination.id
        assert other.user_id == OTHER_USER_ID
