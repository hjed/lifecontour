"""Integration tests for adopting across syncs when a recurrence splits.

When the halves of a split reach the backend in different syncs, the old
recurrence's cancellations land first and the keep-next rule leaves only the
kept "next one" (and any journal the user added to), marked cancelled. A new
instance of the new recurrence then arrives as a create with nothing to tell
it about the old one. If exactly one cancelled journal from another
recurrence sits on its day, in its calendar, under its title, the create
adopts it instead of duplicating it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
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


def _a_week_out_at_noon() -> datetime:
    """Noon UTC (the test user has no zone): every offset these tests add to
    it stays on the same local day, whatever time the suite runs."""
    return (datetime.now(UTC) + timedelta(days=7)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )


async def _seed_and_cancel(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    *,
    weeks: int = 3,
    title: str = "Pilates",
) -> tuple[dict[int, int], dict[int, datetime]]:
    """An old recurrence whose every upcoming week was cancelled."""
    first = _a_week_out_at_noon()
    journals: dict[int, int] = {}
    starts: dict[int, datetime] = {}
    for week in range(1, weeks + 1):
        start = first + timedelta(weeks=week - 1)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_week{week}",
                title=title,
                start=start,
                recurring_event_id=MASTER_ID,
                series_recurring_event_id=MASTER_ID,
            )
        )
        journals[week] = created["journal_id"]
        starts[week] = start
    for week in range(1, weeks + 1):
        await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_week{week}",
                existing_journal_id=journals[week],
                recurring_event_id=MASTER_ID,
            )
        )
    return journals, starts


async def _create_new_instance(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    start: datetime,
    *,
    week: int,
    title: str = "Pilates",
    recurring_event_id: str | None = NEW_MASTER,
) -> int:
    created = await processor.process_event(
        sync_event(
            "journal_event.created",
            calendar_id=calendar_id,
            external_event_id=f"{recurring_event_id or 'single'}_week{week}",
            title=title,
            start=start + timedelta(minutes=10),
            end=start + timedelta(minutes=90),
            etag='"etag-new"',
            recurring_event_id=recurring_event_id,
            series_recurring_event_id=recurring_event_id,
        )
    )
    return int(created["journal_id"])


async def _external_event_id(connection: AsyncConnection, journal_id: int) -> str:
    row = await connection.execute(
        text(
            "SELECT external_event_id FROM journal_external_event_links"
            " WHERE journal_id = :id"
        ),
        {"id": journal_id},
    )
    return str(row.scalar_one())


async def _tag(connection: AsyncConnection, journal_id: int) -> None:
    tag_id = (
        await connection.execute(
            text(
                "INSERT INTO journal_tags (user_id, name) VALUES (:user_id, :name)"
                " RETURNING id"
            ),
            {"user_id": USER_ID, "name": f"tag-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar()
    await connection.execute(
        text(
            "INSERT INTO journal_tag_assignments (journal_id, tag_id)"
            " VALUES (:journal_id, :tag_id)"
        ),
        {"journal_id": journal_id, "tag_id": tag_id},
    )


@pytest.mark.integration
class TestCrossSyncAdoption:
    async def test_the_kept_next_one_is_adopted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id)
        assert [
            w for w in journals if await journal_exists(async_connection, journals[w])
        ] == [1]

        adopted = await _create_new_instance(processor, calendar_id, starts[1], week=1)

        assert adopted == journals[1]
        assert await _external_event_id(async_connection, adopted) == (
            f"{NEW_MASTER}_week1"
        )
        assert await event_state(async_connection, adopted) == "confirmed"

    async def test_a_protected_continuation_is_adopted_too(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        first = _a_week_out_at_noon()
        journals: dict[int, int] = {}
        for week in (1, 2):
            created = await processor.process_event(
                sync_event(
                    "journal_event.created",
                    calendar_id=calendar_id,
                    external_event_id=f"{MASTER_ID}_week{week}",
                    title="Pilates",
                    start=first + timedelta(weeks=week - 1),
                    recurring_event_id=MASTER_ID,
                )
            )
            journals[week] = created["journal_id"]
        await _tag(async_connection, journals[2])
        for week in (1, 2):
            await processor.process_event(
                sync_event(
                    "journal_event.cancelled",
                    calendar_id=calendar_id,
                    external_event_id=f"{MASTER_ID}_week{week}",
                    existing_journal_id=journals[week],
                    recurring_event_id=MASTER_ID,
                )
            )

        adopted = await _create_new_instance(
            processor, calendar_id, first + timedelta(weeks=1), week=2
        )

        assert adopted == journals[2]

    async def test_later_new_instances_join_the_old_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id)

        await _create_new_instance(processor, calendar_id, starts[1], week=1)
        recreated = await _create_new_instance(
            processor, calendar_id, starts[2], week=2
        )

        series_repo = SqlJournalSeriesRepository(async_connection)
        assert len(await series_repo.find_all(USER_ID)) == 1
        [series] = await series_repo.get_series_for_journal(recreated, USER_ID)
        [old_series] = await series_repo.get_series_for_journal(journals[1], USER_ID)
        assert series.id == old_series.id


@pytest.mark.integration
class TestCrossSyncAdoptionRefusals:
    """Anything short of exactly one clear predecessor creates as before."""

    async def test_a_different_title_is_not_adopted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id)

        created = await _create_new_instance(
            processor, calendar_id, starts[1], week=1, title="Yoga"
        )

        assert created != journals[1]

    async def test_another_calendar_is_not_adopted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        other = await create_calendar(async_connection, name="Other")
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id)

        created = await _create_new_instance(processor, other, starts[1], week=1)

        assert created != journals[1]

    async def test_a_single_event_is_not_adopted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id)

        created = await _create_new_instance(
            processor, calendar_id, starts[1], week=1, recurring_event_id=None
        )

        assert created != journals[1]

    async def test_the_same_recurrence_is_not_adopted(
        self, async_connection: AsyncConnection
    ) -> None:
        """A cancelled instance coming back under its own recurrence is not a
        split; it arrives as an update of its own link anyway."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id)

        created = await _create_new_instance(
            processor, calendar_id, starts[1], week=7, recurring_event_id=MASTER_ID
        )

        assert created != journals[1]

    async def test_two_candidates_adopt_neither(
        self, async_connection: AsyncConnection
    ) -> None:
        """Two cancelled "Pilates" from different recurrences on one day."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        start = _a_week_out_at_noon()
        candidates: list[int] = []
        for master, offset in ((MASTER_ID, 0), ("third-master", 5)):
            created = await processor.process_event(
                sync_event(
                    "journal_event.created",
                    calendar_id=calendar_id,
                    external_event_id=f"{master}_week1",
                    title="Pilates",
                    start=start + timedelta(hours=offset),
                    recurring_event_id=master,
                )
            )
            candidates.append(int(created["journal_id"]))
        for master, journal_id in zip(
            (MASTER_ID, "third-master"), candidates, strict=True
        ):
            await processor.process_event(
                sync_event(
                    "journal_event.cancelled",
                    calendar_id=calendar_id,
                    external_event_id=f"{master}_week1",
                    existing_journal_id=journal_id,
                    recurring_event_id=master,
                )
            )

        new_id = await _create_new_instance(processor, calendar_id, start, week=1)

        assert new_id not in candidates

    async def test_a_live_journal_is_not_adopted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        start = _a_week_out_at_noon()
        live = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_week1",
                title="Pilates",
                start=start,
                recurring_event_id=MASTER_ID,
            )
        )

        created = await _create_new_instance(processor, calendar_id, start, week=1)

        assert created != live["journal_id"]


@pytest.mark.integration
class TestAdoptionFromASecondCalendar:
    async def test_only_the_display_calendars_link_is_a_candidate(
        self, async_connection: AsyncConnection
    ) -> None:
        """A journal shared with another calendar keys its series on the one it
        is displayed in; adopting through the other would find no series."""
        calendar_id = await create_calendar(async_connection)
        other = await create_calendar(async_connection, name="Other")
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id, weeks=1)
        await async_connection.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id, recurring_event_id,
                     sync_capability, sync_status, created_at, updated_at)
                VALUES (:journal_id, :calendar_id, 'shared-copy', 'shared-master',
                        'bidirectional', 'cancelled', now(), now())
            """),
            {"journal_id": journals[1], "calendar_id": other},
        )

        created = await _create_new_instance(processor, other, starts[1], week=1)

        assert created != journals[1]


@pytest.mark.integration
class TestPilatesSplitAcrossSyncs:
    """Production as it may have happened: the cancellations in one sync, the
    new recurrence ten hours later in another."""

    async def test_one_series_survivors_adopted_and_nothing_to_review(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals, starts = await _seed_and_cancel(processor, calendar_id, weeks=4)

        new_ids = [
            await _create_new_instance(processor, calendar_id, starts[week], week=week)
            for week in sorted(starts)
        ]

        assert new_ids[0] == journals[1]
        series_repo = SqlJournalSeriesRepository(async_connection)
        [series] = await series_repo.find_all(USER_ID)
        assert series.id is not None
        assert sorted(await series_repo.get_member_journal_ids(series.id)) == sorted(
            new_ids
        )
        # Every candidate for review is gone or live: no cancelled same-day
        # journal is left for match detection to pair a new one with.
        cancelled = await async_connection.execute(
            text("""
                SELECT COUNT(*) FROM journal_calendar_info ci
                JOIN journals j ON j.id = ci.journal_id
                WHERE j.user_id = :user_id AND ci.event_state = 'cancelled'
            """),
            {"user_id": USER_ID},
        )
        assert cancelled.scalar_one() == 0
