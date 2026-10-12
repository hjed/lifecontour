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
class TestLockForMerge:
    async def test_locks_the_users_series_and_returns_the_ids_it_holds(
        self,
        series_repository: SqlJournalSeriesRepository,
        async_connection: AsyncConnection,
    ) -> None:
        mine = await series_repository.save(JournalSeries(user_id=USER_ID, name="A"))
        also_mine = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="B")
        )
        theirs = await series_repository.save(
            JournalSeries(user_id=OTHER_USER_ID, name="C")
        )

        locked = await series_repository.lock_for_merge(
            [_sid(also_mine), _sid(mine), _sid(theirs)], USER_ID
        )

        assert locked == {_sid(mine), _sid(also_mine)}


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

    async def test_a_merged_split_wins_over_the_recurrence_it_split_from(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        """The user merged one split elsewhere; its instances follow that merge."""
        calendar = await _create_calendar(calendar_repository)
        root = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="master",
            name="Root",
        )
        split = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="master_R20260801T090000",
            name="Split",
        )
        destination = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Destination")
        )
        await series_repository.alias_recurrences(split, _sid(destination))
        await series_repository.delete(_sid(split), USER_ID)

        merged_split = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="master",
            name="Must not be used",
            split_recurring_event_id="master_R20260801T090000",
        )
        unmerged_split = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="master",
            name="Must not be used",
            split_recurring_event_id="master_R20261001T090000",
        )

        assert merged_split.id == destination.id
        assert unmerged_split.id == root.id

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


@pytest.mark.integration
class TestAdoptRecurrence:
    """A recurrence Google split off under an unrelated id joins the old series."""

    async def _old_series(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar: Calendar,
    ) -> JournalSeries:
        return await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="old-master",
            name="Pilates",
        )

    async def test_later_instances_of_the_new_recurrence_join_the_old_series(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)
        old = await self._old_series(series_repository, calendar)

        adopted_into = await series_repository.adopt_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            into_recurring_event_id="old-master",
        )

        assert adopted_into == old.id
        resolved = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            name="Pilates (new)",
        )
        assert resolved.id == old.id
        assert [s.id for s in await series_repository.find_all(USER_ID)] == [old.id]

    async def test_a_series_already_started_for_the_new_recurrence_is_folded_in(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)
        old = await self._old_series(series_repository, calendar)
        started = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            name="Pilates",
        )
        member = await _create_journal(journal_repository)
        assert member.id is not None
        await series_repository.add_member(_sid(started), member.id)

        await series_repository.adopt_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            into_recurring_event_id="old-master",
        )

        assert await series_repository.find_by_id(_sid(started), USER_ID) is None
        assert await series_repository.get_member_journal_ids(_sid(old)) == [member.id]

    async def test_the_old_series_is_found_through_its_merge(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        """The old recurrence was merged into a manual series: adopt into that."""
        calendar = await _create_calendar(calendar_repository)
        old = await self._old_series(series_repository, calendar)
        manual = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Pilates (all)")
        )
        await series_repository.alias_recurrences(old, _sid(manual))
        await series_repository.delete(_sid(old), USER_ID)

        adopted_into = await series_repository.adopt_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            into_recurring_event_id="old-master",
        )

        assert adopted_into == manual.id

    async def test_no_old_series_adopts_nothing(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        calendar = await _create_calendar(calendar_repository)

        adopted_into = await series_repository.adopt_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            into_recurring_event_id="old-master",
        )

        assert adopted_into is None
        assert await series_repository.find_all(USER_ID) == []


@pytest.mark.integration
class TestAdoptRecurrenceRaces:
    """Interleavings ``adopt_recurrence`` must survive, forced with patches."""

    async def test_a_series_merged_away_before_its_lock_keeps_its_alias(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        """A series merge absorbs the new recurrence's series between the
        lookup and the row lock: follow where it went, don't overwrite it."""
        from unittest.mock import patch

        calendar = await _create_calendar(calendar_repository)
        old = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="old-master",
            name="Pilates",
        )
        started = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            name="Pilates",
        )
        elsewhere = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Studio classes")
        )
        real_lock = series_repository.lock_for_merge

        async def merged_meanwhile(
            series_ids: list[uuid.UUID], user_id: str
        ) -> set[uuid.UUID]:
            await series_repository.alias_recurrences(started, _sid(elsewhere))
            await series_repository.delete(_sid(started), USER_ID)
            return await real_lock(series_ids, user_id)

        with patch.object(series_repository, "lock_for_merge", merged_meanwhile):
            adopted_into = await series_repository.adopt_recurrence(
                user_id=USER_ID,
                calendar_id=_cid(calendar),
                recurring_event_id="new-master",
                into_recurring_event_id="old-master",
            )

        assert adopted_into == elsewhere.id
        resolved = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            name="Pilates",
        )
        assert resolved.id == elsewhere.id
        assert await series_repository.find_by_id(_sid(old), USER_ID) is not None

    async def test_a_series_created_while_waiting_for_the_key_is_left_alone(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        """Folding it would take series row locks after the key lock, the
        reverse of a series merge's order: leave it for the user to merge."""
        from unittest.mock import patch

        calendar = await _create_calendar(calendar_repository)
        await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="old-master",
            name="Pilates",
        )
        real_find = series_repository._find_by_key
        new_key_reads = 0

        async def created_meanwhile(
            user_id: str, calendar_id: uuid.UUID, recurring_event_id: str
        ) -> JournalSeries | None:
            nonlocal new_key_reads
            if recurring_event_id == "new-master":
                new_key_reads += 1
                if new_key_reads == 1:
                    return None
                if new_key_reads == 2:
                    # Another consumer's create commits while this one waits.
                    await series_repository.conn.execute(
                        text(
                            "INSERT INTO journal_series"
                            " (user_id, name, calendar_id, recurring_event_id)"
                            " VALUES (:user_id, 'Pilates', :calendar_id, 'new-master')"
                        ),
                        {"user_id": USER_ID, "calendar_id": _cid(calendar)},
                    )
            return await real_find(user_id, calendar_id, recurring_event_id)

        with (
            patch.object(series_repository, "_find_by_key", created_meanwhile),
            patch.object(series_repository, "lock_for_merge") as lock_for_merge,
        ):
            adopted_into = await series_repository.adopt_recurrence(
                user_id=USER_ID,
                calendar_id=_cid(calendar),
                recurring_event_id="new-master",
                into_recurring_event_id="old-master",
            )

        assert adopted_into is None
        lock_for_merge.assert_not_called()
        assert len(await series_repository.find_all(USER_ID)) == 2

    async def test_an_old_series_merged_away_before_its_lock_is_followed(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        """The old recurrence's series is merged into a manual one between the
        lookup and the row lock: fold into where it went."""
        from unittest.mock import patch

        calendar = await _create_calendar(calendar_repository)
        old = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="old-master",
            name="Pilates",
        )
        started = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            name="Pilates",
        )
        manual = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Pilates (all)")
        )
        real_lock = series_repository.lock_for_merge
        merged = False

        async def merged_meanwhile(
            series_ids: list[uuid.UUID], user_id: str
        ) -> set[uuid.UUID]:
            nonlocal merged
            if not merged:
                merged = True
                await series_repository.alias_recurrences(old, _sid(manual))
                await series_repository.delete(_sid(old), USER_ID)
            return await real_lock(series_ids, user_id)

        with patch.object(series_repository, "lock_for_merge", merged_meanwhile):
            adopted_into = await series_repository.adopt_recurrence(
                user_id=USER_ID,
                calendar_id=_cid(calendar),
                recurring_event_id="new-master",
                into_recurring_event_id="old-master",
            )

        assert adopted_into == manual.id
        assert await series_repository.find_by_id(_sid(started), USER_ID) is None


@pytest.mark.integration
class TestAdoptRecurrenceFromASplit:
    async def test_a_split_merged_elsewhere_adopts_into_where_it_went(
        self,
        series_repository: SqlJournalSeriesRepository,
        calendar_repository: SqlCalendarRepository,
    ) -> None:
        """The old link's recurrence was itself a split the user merged into
        another series; its root still has its own. Resolve as
        ``get_or_create_by_recurrence`` does: the split's alias first."""
        calendar = await _create_calendar(calendar_repository)
        root = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="old-master",
            name="Pilates",
        )
        elsewhere = await series_repository.save(
            JournalSeries(user_id=USER_ID, name="Evening classes")
        )
        split_series = await series_repository.get_or_create_by_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="old-master_R20260801T090000",
            name="Pilates",
        )
        await series_repository.alias_recurrences(split_series, _sid(elsewhere))
        await series_repository.delete(_sid(split_series), USER_ID)

        adopted_into = await series_repository.adopt_recurrence(
            user_id=USER_ID,
            calendar_id=_cid(calendar),
            recurring_event_id="new-master",
            into_recurring_event_id="old-master",
            into_split_recurring_event_id="old-master_R20260801T090000",
        )

        assert adopted_into == elsewhere.id
        assert adopted_into != root.id
