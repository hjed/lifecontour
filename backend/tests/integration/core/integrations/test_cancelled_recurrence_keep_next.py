"""Integration tests for the keep-next rule on a cancelled recurrence.

A recurrence Google truncates or deletes arrives as one cancellation per
upcoming occurrence. Whatever order those arrive in, the first not-yet-started
occurrence of each unbroken cancelled run is kept, marked cancelled, and every
later one is deleted - unless the user has added to it.

Seeded through the real processor, so the links, calendar info and series
membership are the ones a sync writes.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from tests.integration.core.integrations.journal_sync_seeding import (
    MASTER_ID,
    USER_ID,
    build_processor,
    create_calendar,
    event_state,
    journal_exists,
    link_recurring_id,
    series_cancelled_event,
    sync_event,
)
from tests.integration.tasks.task_seeding import create_task

WEEKS = 5


def _instance_id(week: int, master_id: str = MASTER_ID) -> str:
    return f"{master_id}_2027010{week}T011000Z"


async def _seed_weekly(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    *,
    weeks: int = WEEKS,
    recurring_event_id: str | None = MASTER_ID,
) -> dict[int, int]:
    """Weekly occurrences from a week out: week number -> journal id."""
    first = datetime.now(UTC) + timedelta(days=7)
    journals: dict[int, int] = {}
    for week in range(1, weeks + 1):
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=_instance_id(week),
                start=first + timedelta(weeks=week - 1),
                recurring_event_id=recurring_event_id,
            )
        )
        journals[week] = created["journal_id"]
    return journals


async def _cancel(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    journals: dict[int, int],
    week: int,
    *,
    recurring_event_id: str | None = MASTER_ID,
) -> dict[str, object]:
    return await processor.process_event(
        sync_event(
            "journal_event.cancelled",
            calendar_id=calendar_id,
            external_event_id=_instance_id(week),
            existing_journal_id=journals[week],
            recurring_event_id=recurring_event_id,
        )
    )


async def _surviving_weeks(
    connection: AsyncConnection, journals: dict[int, int]
) -> list[int]:
    return [
        week
        for week, journal_id in sorted(journals.items())
        if await journal_exists(connection, journal_id)
    ]


async def _record_history(
    connection: AsyncConnection, journal_id: int, source: str
) -> None:
    """A history row as the projection consumer writes it for an edit."""
    await connection.execute(
        text("""
            INSERT INTO field_history
                (entity_type, entity_id, field_name, old_value, new_value,
                 changed_by, source, event_id, user_id)
            VALUES ('journal', :journal_id, 'content', '', 'my notes',
                    :source, :source, :event_id, :user_id)
        """),
        {
            "journal_id": journal_id,
            "source": source,
            "event_id": f"evt-{uuid.uuid4()}",
            "user_id": USER_ID,
        },
    )


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
class TestCancelledTail:
    async def test_a_tail_cancelled_out_of_order_keeps_only_its_first(
        self, async_connection: AsyncConnection
    ) -> None:
        """The far end of the tail arriving first is deleted once its run
        joins the first cancelled occurrence's."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id)

        for week in (5, 3, 4, 2):
            await _cancel(processor, calendar_id, journals, week)

        assert await _surviving_weeks(async_connection, journals) == [1, 2]
        assert await event_state(async_connection, journals[1]) != "cancelled"
        assert await event_state(async_connection, journals[2]) == "cancelled"

    async def test_one_cancelled_occurrence_is_kept(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=3)

        result = await _cancel(processor, calendar_id, journals, 2)

        assert result.get("action") != "deleted"
        assert await _surviving_weeks(async_connection, journals) == [1, 2, 3]
        assert await event_state(async_connection, journals[2]) == "cancelled"

    async def test_the_cancelled_occurrence_itself_is_reported_deleted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=3)
        await _cancel(processor, calendar_id, journals, 2)

        result = await _cancel(processor, calendar_id, journals, 3)

        assert result["action"] == "deleted"
        assert result["journal_id"] == journals[3]

    async def test_a_redelivered_cancellation_keeps_the_next_one(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=3)

        await _cancel(processor, calendar_id, journals, 2)
        await _cancel(processor, calendar_id, journals, 2)

        assert await _surviving_weeks(async_connection, journals) == [1, 2, 3]

    async def test_an_untouched_journal_newer_than_its_link_is_deleted(
        self, async_connection: AsyncConnection
    ) -> None:
        """The production case: a journal merge bumped every occurrence's
        updated_at past its link's, and the old timestamp guard read that as
        a local edit and kept the whole tail."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=3)
        await async_connection.execute(
            text("UPDATE journals SET updated_at = :ts WHERE id = ANY(:ids)"),
            {
                "ts": datetime.now(UTC) + timedelta(hours=1),
                "ids": list(journals.values()),
            },
        )

        for week in (2, 3):
            await _cancel(processor, calendar_id, journals, week)

        assert await _surviving_weeks(async_connection, journals) == [1, 2]

    async def test_review_items_go_with_a_deleted_continuation(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=3)
        await async_connection.execute(
            text("""
                INSERT INTO journal_review_items
                    (user_id, source_journal_id, candidate_journal_id,
                     reason, confidence_score, status)
                VALUES (:user_id, :source, :candidate,
                        'duplicate_journal', 0.8, 'pending')
            """),
            {"user_id": USER_ID, "source": journals[3], "candidate": journals[1]},
        )

        for week in (2, 3):
            await _cancel(processor, calendar_id, journals, week)

        remaining = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM journal_review_items"
                " WHERE source_journal_id = :id"
            ),
            {"id": journals[3]},
        )
        assert remaining.scalar() == 0


@pytest.mark.integration
class TestProtectedContinuations:
    """A continuation the user has added to is kept, marked cancelled."""

    async def _cancel_tail_after(
        self, connection: AsyncConnection, protect: str
    ) -> tuple[dict[int, int], int]:
        calendar_id = await create_calendar(connection)
        processor = build_processor(connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=4)
        protected = journals[3]
        if protect == "tag":
            await _tag(connection, protected)
        elif protect == "task":
            await create_task(
                connection,
                creating_journal_id=protected,
                due_journal_id=protected,
                user_id=USER_ID,
            )
        elif protect in ("ui", "mcp"):
            await _record_history(connection, protected, protect)
        elif protect == "second_calendar":
            other_calendar = await create_calendar(connection, name="Other")
            await connection.execute(
                text("""
                    INSERT INTO journal_external_event_links
                        (journal_id, calendar_id, external_event_id,
                         sync_capability, sync_status, created_at, updated_at)
                    VALUES (:journal_id, :calendar_id, 'other-copy',
                            'bidirectional', 'synced', now(), now())
                """),
                {"journal_id": protected, "calendar_id": other_calendar},
            )

        for week in (4, 3, 2):
            await _cancel(processor, calendar_id, journals, week)
        return journals, protected

    @pytest.mark.parametrize("protect", ["tag", "task", "ui", "mcp"])
    async def test_a_user_addition_keeps_a_continuation_cancelled(
        self, async_connection: AsyncConnection, protect: str
    ) -> None:
        journals, protected = await self._cancel_tail_after(async_connection, protect)

        assert await _surviving_weeks(async_connection, journals) == [1, 2, 3]
        assert await event_state(async_connection, protected) == "cancelled"

    async def test_a_second_calendar_still_holding_the_event_keeps_it(
        self, async_connection: AsyncConnection
    ) -> None:
        journals, protected = await self._cancel_tail_after(
            async_connection, "second_calendar"
        )

        assert await _surviving_weeks(async_connection, journals) == [1, 2, 3]
        # The other calendar still holds it, so the journal itself is live.
        assert await event_state(async_connection, protected) != "cancelled"

    @pytest.mark.parametrize("source", ["google_calendar", "system"])
    async def test_sync_and_system_history_does_not_protect(
        self, async_connection: AsyncConnection, source: str
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=3)
        await _record_history(async_connection, journals[3], source)

        for week in (2, 3):
            await _cancel(processor, calendar_id, journals, week)

        assert await _surviving_weeks(async_connection, journals) == [1, 2]


@pytest.mark.integration
class TestSeriesCancelledKeepsNext:
    async def test_a_deleted_series_keeps_its_earliest_upcoming_occurrence(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id)

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["deleted"] == WEEKS - 1
        assert result["cancelled"] == 1
        assert await _surviving_weeks(async_connection, journals) == [1]
        assert await event_state(async_connection, journals[1]) == "cancelled"

    async def test_a_repeated_series_cancellation_changes_nothing_more(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(processor, calendar_id, weeks=3)
        await _record_history(async_connection, journals[3], "ui")

        await processor.process_event(series_cancelled_event(calendar_id))
        second = await processor.process_event(series_cancelled_event(calendar_id))

        assert second["deleted"] == 0
        assert await _surviving_weeks(async_connection, journals) == [1, 3]

    async def test_legacy_links_are_backfilled_and_planned(
        self, async_connection: AsyncConnection
    ) -> None:
        """Links synced before the recurring id was recorded are matched by
        their instance-id prefix, given the id, and planned like the rest."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(
            processor, calendar_id, weeks=3, recurring_event_id=None
        )
        assert await link_recurring_id(async_connection, journals[1]) is None

        await processor.process_event(series_cancelled_event(calendar_id))

        assert await _surviving_weeks(async_connection, journals) == [1]
        assert await link_recurring_id(async_connection, journals[1]) == MASTER_ID


@pytest.mark.integration
class TestLegacyInstanceCancellation:
    async def test_a_cancel_carrying_the_recurring_id_plans_legacy_links(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journals = await _seed_weekly(
            processor, calendar_id, weeks=3, recurring_event_id=None
        )

        for week in (3, 2):
            await _cancel(processor, calendar_id, journals, week)

        assert await _surviving_weeks(async_connection, journals) == [1, 2]
