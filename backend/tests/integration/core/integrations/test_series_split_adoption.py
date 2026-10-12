"""Integration tests for adopting a journal across a split recurrence.

Google can answer a "this and following" edit by ending the old recurrence and
starting a new one under an unrelated id. The Google worker pairs the two
halves when they arrive in one sync, and sends the new instance as an update
of the old journal carrying ``split_adopted_from``. The journal must come out
re-pointed - new event, new times, same journal, same series - with the user's
title and notes intact and no duplicate or review item anywhere.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.journal.models.journal_series import JournalSeries
from tests.integration.core.integrations.journal_sync_seeding import (
    MASTER_ID,
    USER_ID,
    build_processor,
    create_calendar,
    event_state,
    journal_exists,
    sync_event,
)

NEW_MASTER = "9p7kac2r5m992mshlenq0j10pf"


async def _seed_old_recurrence(
    processor: JournalOutboxEventProcessor, calendar_id: str, weeks: int = 3
) -> tuple[dict[int, int], dict[int, datetime]]:
    first = datetime.now(UTC).replace(microsecond=0) + timedelta(days=7)
    journals: dict[int, int] = {}
    starts: dict[int, datetime] = {}
    for week in range(1, weeks + 1):
        start = first + timedelta(weeks=week - 1)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_week{week}",
                title="Pilates",
                start=start,
                recurring_event_id=MASTER_ID,
                series_recurring_event_id=MASTER_ID,
            )
        )
        journals[week] = created["journal_id"]
        starts[week] = start
    return journals, starts


async def _adopt(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    *,
    journal_id: int,
    start: datetime,
    week: int,
) -> dict[str, object]:
    """The worker's adopting update: new id and times, aimed at the old journal."""
    return await processor.process_event(
        sync_event(
            "journal_event.updated",
            calendar_id=calendar_id,
            external_event_id=f"{NEW_MASTER}_week{week}",
            title="Pilates",
            start=start + timedelta(minutes=10),
            end=start + timedelta(minutes=90),
            etag='"etag-new"',
            existing_journal_id=journal_id,
            recurring_event_id=NEW_MASTER,
            series_recurring_event_id=NEW_MASTER,
            split_adopted_from=MASTER_ID,
        )
    )


async def _cancel(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    journals: dict[int, int],
    week: int,
) -> None:
    await processor.process_event(
        sync_event(
            "journal_event.cancelled",
            calendar_id=calendar_id,
            external_event_id=f"{MASTER_ID}_week{week}",
            existing_journal_id=journals[week],
            recurring_event_id=MASTER_ID,
        )
    )


async def _link(connection: AsyncConnection, journal_id: int) -> tuple[str, str, str]:
    row = (
        await connection.execute(
            text("""
                SELECT external_event_id, recurring_event_id, sync_status
                FROM journal_external_event_links WHERE journal_id = :id
            """),
            {"id": journal_id},
        )
    ).one()
    return row.external_event_id, row.recurring_event_id, row.sync_status


async def _journal_count(connection: AsyncConnection) -> int:
    count = await connection.execute(
        text("SELECT COUNT(*) FROM journals WHERE user_id = :user_id"),
        {"user_id": USER_ID},
    )
    return int(count.scalar_one())


@pytest.mark.integration
class TestAdoptingUpdate:
    async def test_the_old_journal_is_repointed_in_place(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        series_repo = SqlJournalSeriesRepository(async_connection)
        [old_series] = await series_repo.get_series_for_journal(journals[2], USER_ID)

        result = await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        assert result["journal_id"] == journals[2]
        assert await _link(async_connection, journals[2]) == (
            f"{NEW_MASTER}_week2",
            NEW_MASTER,
            "synced",
        )
        moved = await async_connection.execute(
            text("SELECT event_date_range_start FROM journals WHERE id = :id"),
            {"id": journals[2]},
        )
        assert moved.scalar_one() == starts[2] + timedelta(minutes=10)
        assert await event_state(async_connection, journals[2]) == "confirmed"
        assert await _journal_count(async_connection) == 3
        assert [
            s.id for s in await series_repo.get_series_for_journal(journals[2], USER_ID)
        ] == [old_series.id]

    async def test_a_previously_cancelled_journal_is_live_again(
        self, async_connection: AsyncConnection
    ) -> None:
        """Adoption is how the kept "next one" comes back when the halves of
        the split reach the backend in that order."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        await _cancel(processor, calendar_id, journals, 2)

        await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        assert await event_state(async_connection, journals[2]) == "confirmed"
        assert (await _link(async_connection, journals[2]))[2] == "synced"

    async def test_the_users_title_and_notes_survive(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        await async_connection.execute(
            text(
                "UPDATE journals SET title = 'pilates (studio 2)',"
                " content = 'Bring a mat' WHERE id = :id"
            ),
            {"id": journals[2]},
        )

        await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        row = (
            await async_connection.execute(
                text("SELECT title, content FROM journals WHERE id = :id"),
                {"id": journals[2]},
            )
        ).one()
        assert (row.title, row.content) == ("pilates (studio 2)", "Bring a mat")

    async def test_later_instances_of_the_new_recurrence_join_the_old_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        later = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{NEW_MASTER}_week9",
                title="Pilates",
                start=starts[3] + timedelta(weeks=6),
                recurring_event_id=NEW_MASTER,
                series_recurring_event_id=NEW_MASTER,
            )
        )

        series_repo = SqlJournalSeriesRepository(async_connection)
        assert [s.name for s in await series_repo.find_all(USER_ID)] == ["Pilates"]
        [later_series] = await series_repo.get_series_for_journal(
            int(later["journal_id"]), USER_ID
        )
        [old_series] = await series_repo.get_series_for_journal(journals[1], USER_ID)
        assert later_series.id == old_series.id

    async def test_no_match_detection_is_requested(
        self, async_connection: AsyncConnection
    ) -> None:
        """Adoption is an update: nothing new arrived to be checked for doubles."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        before = await self._detect_requests(async_connection)

        await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        assert await self._detect_requests(async_connection) == before

    @staticmethod
    async def _detect_requests(connection: AsyncConnection) -> int:
        count = await connection.execute(
            text(
                "SELECT COUNT(*) FROM outbox_events"
                " WHERE event_type = 'journal_review.detect_matches'"
            )
        )
        return int(count.scalar_one())


@pytest.mark.integration
class TestTheOldRecurrenceAfterAdoption:
    async def test_a_continuation_left_behind_is_deleted(
        self, async_connection: AsyncConnection
    ) -> None:
        """Week 3 was kept while week 2 was live. Week 2 leaving the old
        recurrence makes week 3 a continuation of week 1's cancelled run."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        await _cancel(processor, calendar_id, journals, 1)
        await _cancel(processor, calendar_id, journals, 3)
        assert await journal_exists(async_connection, journals[3])

        await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        assert await journal_exists(async_connection, journals[1])
        assert await journal_exists(async_connection, journals[2])
        assert not await journal_exists(async_connection, journals[3])


@pytest.mark.integration
class TestAStaleCancellationAfterAdoption:
    async def test_it_does_not_cancel_the_adopted_event(
        self, async_connection: AsyncConnection
    ) -> None:
        """The old instance's cancellation, retried after the adoption, names
        an event the journal no longer links to: it is stale, not news."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        result = await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_week2",
                existing_journal_id=journals[2],
                recurring_event_id=MASTER_ID,
            )
        )

        assert result["status"] == "skipped"
        assert await event_state(async_connection, journals[2]) == "confirmed"
        assert (await _link(async_connection, journals[2]))[2] == "synced"


@pytest.mark.integration
class TestAdoptionFallback:
    async def test_a_deleted_target_is_created_instead(
        self, async_connection: AsyncConnection
    ) -> None:
        """The worker has moved past this event: losing it would be permanent."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        await async_connection.execute(
            text("DELETE FROM journals WHERE id = :id"), {"id": journals[2]}
        )

        result = await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        assert result["status"] == "success"
        created = int(result["journal_id"])  # type: ignore[call-overload]
        assert created != journals[2]
        assert (await _link(async_connection, created))[0] == f"{NEW_MASTER}_week2"
        content = await async_connection.execute(
            text("SELECT content FROM journals WHERE id = :id"), {"id": created}
        )
        assert content.scalar_one() == "Synced from Google Calendar"

    async def test_the_created_instance_joins_the_old_series(
        self, async_connection: AsyncConnection
    ) -> None:
        """The payload still names the old series, so it is not abandoned."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id)
        series_repo = SqlJournalSeriesRepository(async_connection)
        [old_series] = await series_repo.get_series_for_journal(journals[1], USER_ID)
        await async_connection.execute(
            text("DELETE FROM journals WHERE id = :id"), {"id": journals[2]}
        )

        result = await _adopt(
            processor, calendar_id, journal_id=journals[2], start=starts[2], week=2
        )

        created = int(result["journal_id"])  # type: ignore[call-overload]
        assert [
            s.id for s in await series_repo.get_series_for_journal(created, USER_ID)
        ] == [old_series.id]
        assert len(await series_repo.find_all(USER_ID)) == 1


@pytest.mark.integration
class TestPilatesSplitInOneSync:
    """The production case: Pilates moved from 12:10 to 12:20 for every
    remaining week, under a new recurrence id, all in one sync."""

    async def test_every_week_is_updated_in_place(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_old_recurrence(processor, calendar_id, weeks=4)
        detect_before = await TestAdoptingUpdate._detect_requests(async_connection)

        for week in journals:
            await _adopt(
                processor,
                calendar_id,
                journal_id=journals[week],
                start=starts[week],
                week=week,
            )

        assert await _journal_count(async_connection) == 4
        for week, journal_id in journals.items():
            assert await _link(async_connection, journal_id) == (
                f"{NEW_MASTER}_week{week}",
                NEW_MASTER,
                "synced",
            )
            assert await event_state(async_connection, journal_id) == "confirmed"
        series_repo = SqlJournalSeriesRepository(async_connection)
        [series] = await series_repo.find_all(USER_ID)
        assert sorted(await series_repo.get_member_journal_ids(_series_id(series))) == (
            sorted(journals.values())
        )
        assert (
            await TestAdoptingUpdate._detect_requests(async_connection) == detect_before
        )


def _series_id(series: JournalSeries) -> UUID:
    assert series.id is not None
    return series.id
