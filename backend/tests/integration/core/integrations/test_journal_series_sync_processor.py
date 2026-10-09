"""Integration tests for recurring-series sync in JournalOutboxEventProcessor.

Covers series auto-linking on create, recurring-id backfill on update,
whole-series cancellation fan-out (delete far-future, cancel near, skip past),
local-edit protection, and the external-event-id prefix fallback for links
synced before the recurring id was recorded.

The harness that builds the processor and its outbox payloads lives in
``journal_sync_seeding``, because the task-cancellation tests drive the same
path from ``tests/integration/tasks/``.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessingError,
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
    link_recurring_id,
    series_cancelled_event,
    sync_event,
)
from tests.integration.tasks.task_seeding import create_task


@pytest.mark.integration
class TestSeriesAutoLinkingOnCreate:
    async def test_recurring_instances_link_into_one_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260801T090000Z",
                recurring_event_id=MASTER_ID,
            )
        )
        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260808T090000Z",
                recurring_event_id=MASTER_ID,
            )
        )

        series_repo = SqlJournalSeriesRepository(async_connection)
        first_series = await series_repo.get_series_for_journal(
            first["journal_id"], USER_ID
        )
        second_series = await series_repo.get_series_for_journal(
            second["journal_id"], USER_ID
        )
        assert len(first_series) == 1
        assert first_series[0].name == "Physio appointment"
        assert first_series[0].auto_created is True
        assert [s.id for s in first_series] == [s.id for s in second_series]
        assert await link_recurring_id(async_connection, first["journal_id"]) == (
            MASTER_ID
        )

    async def test_non_recurring_event_creates_no_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        result = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="single-event-1",
            )
        )

        series_repo = SqlJournalSeriesRepository(async_connection)
        assert (
            await series_repo.get_series_for_journal(result["journal_id"], USER_ID)
            == []
        )


@pytest.mark.integration
class TestSplitRecurrence:
    """A "this and following" edit splits one recurrence into two masters."""

    SPLIT_ID = f"{MASTER_ID}_R20260815T090000"

    async def test_instances_of_every_split_share_one_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        before = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260808T090000Z",
                recurring_event_id=MASTER_ID,
                series_recurring_event_id=MASTER_ID,
            )
        )
        after = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{self.SPLIT_ID}_20260815T090000Z",
                recurring_event_id=self.SPLIT_ID,
                series_recurring_event_id=MASTER_ID,
            )
        )

        series_repo = SqlJournalSeriesRepository(async_connection)
        [series] = await series_repo.find_all(USER_ID)
        assert series.recurring_event_id == MASTER_ID
        assert [
            s.id
            for s in await series_repo.get_series_for_journal(
                after["journal_id"], USER_ID
            )
        ] == [series.id]
        assert [
            s.id
            for s in await series_repo.get_series_for_journal(
                before["journal_id"], USER_ID
            )
        ] == [series.id]
        # The link keeps the split's own id: cancellation is scoped by it.
        assert await link_recurring_id(async_connection, after["journal_id"]) == (
            self.SPLIT_ID
        )

    async def test_cancelling_a_split_leaves_the_other_split_alone(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        before = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260808T090000Z",
                recurring_event_id=MASTER_ID,
                series_recurring_event_id=MASTER_ID,
            )
        )
        after = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{self.SPLIT_ID}_20260815T090000Z",
                recurring_event_id=self.SPLIT_ID,
                series_recurring_event_id=MASTER_ID,
            )
        )

        result = await processor.process_event(
            series_cancelled_event(calendar_id, master_id=self.SPLIT_ID)
        )

        assert result["deleted"] == 1
        assert not await journal_exists(async_connection, after["journal_id"])
        assert await journal_exists(async_connection, before["journal_id"])
        assert await event_state(async_connection, before["journal_id"]) != (
            "cancelled"
        )


@pytest.mark.integration
class TestSeriesAutoLinkingAfterSeriesMerge:
    async def test_new_instance_of_a_merged_recurrence_joins_the_survivor(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260801T090000Z",
                recurring_event_id=MASTER_ID,
            )
        )
        series_repo = SqlJournalSeriesRepository(async_connection)
        [merged_away] = await series_repo.get_series_for_journal(
            first["journal_id"], USER_ID
        )
        survivor = await series_repo.save(
            JournalSeries(user_id=USER_ID, name="Survivor")
        )
        assert survivor.id is not None and merged_away.id is not None
        await series_repo.alias_recurrences(merged_away, survivor.id)
        await series_repo.delete(merged_away.id, USER_ID)

        later = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260808T090000Z",
                recurring_event_id=MASTER_ID,
            )
        )

        later_series = await series_repo.get_series_for_journal(
            later["journal_id"], USER_ID
        )
        assert [s.id for s in later_series] == [survivor.id]
        assert [s.name for s in await series_repo.find_all(USER_ID)] == ["Survivor"]


@pytest.mark.integration
class TestRecurringIdBackfillOnUpdate:
    async def test_promoted_update_populates_recurring_id_and_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        external_event_id = f"{MASTER_ID}_20260801T090000Z"

        # Synced before the series feature: no recurring id on the wire.
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
            )
        )
        journal_id = created["journal_id"]
        assert await link_recurring_id(async_connection, journal_id) is None

        # Re-seen with a recurring id (backfill promotion) and a new etag.
        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                etag='"etag-2"',
                recurring_event_id=MASTER_ID,
            )
        )

        assert await link_recurring_id(async_connection, journal_id) == MASTER_ID
        series_repo = SqlJournalSeriesRepository(async_connection)
        series = await series_repo.get_series_for_journal(journal_id, USER_ID)
        assert len(series) == 1
        assert series[0].recurring_event_id == MASTER_ID


@pytest.mark.integration
class TestSeriesCancelledFanOut:
    async def test_deletes_future_cancels_near_skips_past(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        now = datetime.now(UTC)

        journals: dict[str, int] = {}
        for key, start in (
            ("future", now + timedelta(days=10)),
            ("near", now + timedelta(hours=6)),
            ("past", now - timedelta(days=10)),
        ):
            result = await processor.process_event(
                sync_event(
                    "journal_event.created",
                    calendar_id=calendar_id,
                    external_event_id=f"{MASTER_ID}_{key}",
                    start=start,
                    recurring_event_id=MASTER_ID,
                )
            )
            journals[key] = result["journal_id"]

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["status"] == "success"
        assert result["deleted"] == 1
        assert result["cancelled"] == 1
        assert result["skipped_past"] == 1
        assert result["errors"] == 0
        assert not await journal_exists(async_connection, journals["future"])
        assert await journal_exists(async_connection, journals["near"])
        assert await event_state(async_connection, journals["near"]) == "cancelled"
        assert await journal_exists(async_connection, journals["past"])
        assert await event_state(async_connection, journals["past"]) != "cancelled"

    async def test_edited_future_journal_preserved_as_cancelled(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_edited",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]

        # Local edit after the sync: journal updated_at newer than the link's.
        await async_connection.execute(
            text(
                "UPDATE journals SET content = 'my notes', updated_at = :ts"
                " WHERE id = :id"
            ),
            {"ts": datetime.now(UTC) + timedelta(seconds=30), "id": journal_id},
        )

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"

    async def test_prefix_fallback_matches_unbackfilled_links(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        # Link synced before the series feature: no recurring id stored, but
        # the Google instance id embeds the master id as a prefix.
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260901T090000Z",
            )
        )
        journal_id = created["journal_id"]
        assert await link_recurring_id(async_connection, journal_id) is None

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["deleted"] == 1
        assert not await journal_exists(async_connection, journal_id)

    async def test_no_links_is_noop_success(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        result = await processor.process_event(
            series_cancelled_event(calendar_id, master_id="unknown-master")
        )

        assert result["status"] == "success"
        assert result["deleted"] == 0
        assert result["cancelled"] == 0


@pytest.mark.integration
class TestRecurringInstanceCancellation:
    async def test_cancelled_future_instance_is_deleted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        external_event_id = f"{MASTER_ID}_instance1"

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]

        result = await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                recurring_event_id=MASTER_ID,
            )
        )

        assert result["action"] == "deleted"
        assert not await journal_exists(async_connection, journal_id)

    async def test_cancelled_tagged_instance_falls_back_to_cancel(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        external_event_id = f"{MASTER_ID}_instance2"

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]

        # A tag is a local addition — deletion would lose user data.
        tag_id = (
            await async_connection.execute(
                text(
                    "INSERT INTO journal_tags (user_id, name) VALUES ('test-user-123', :name) RETURNING id"
                ),
                {"name": f"tag-{uuid.uuid4().hex[:8]}"},
            )
        ).scalar()
        await async_connection.execute(
            text(
                "INSERT INTO journal_tag_assignments (journal_id, tag_id)"
                " VALUES (:journal_id, :tag_id)"
            ),
            {"journal_id": journal_id, "tag_id": tag_id},
        )

        result = await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                recurring_event_id=MASTER_ID,
            )
        )

        assert result.get("action") != "deleted"
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"

    async def test_cancelled_instance_a_task_is_due_in_falls_back_to_cancel(
        self, async_connection: AsyncConnection
    ) -> None:
        """A single instance cancelled upstream takes the same fallback as the
        whole-series fan-out.

        An anchored task is a normal state of the world, not a failure, so the
        event must reach its cancellation outcome rather than being retried
        forever over a journal that is never going to become deletable.
        """
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        external_event_id = f"{MASTER_ID}_anchored_instance"

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
            user_id=USER_ID,
        )

        result = await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                recurring_event_id=MASTER_ID,
            )
        )

        assert result.get("action") != "deleted"
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"
        # The task kept its anchor, and the external link the deletion attempt
        # had already removed came back with the savepoint.
        surviving = await async_connection.execute(
            text("SELECT due_journal_id FROM tasks WHERE id = :task_id"),
            {"task_id": task_id},
        )
        assert surviving.scalar() == journal_id
        assert await link_recurring_id(async_connection, journal_id) == MASTER_ID


@pytest.mark.integration
class TestSeriesCancelledWithAnchoredTasks:
    async def test_an_instance_a_task_is_due_in_is_cancelled_not_deleted(
        self, async_connection: AsyncConnection
    ) -> None:
        """A far-future instance is exactly the profile of a task's due journal.

        Deleting it would destroy a commitment the user made, so the delete
        guard refuses — and the sync falls back to marking the instance
        cancelled, the same outcome as a journal the deletion heuristics
        protect. The event must still succeed: an anchored task is a normal
        state of the world, not a failure to retry.
        """
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_anchored",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
            user_id=USER_ID,
        )

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"
        # The task is untouched — cancelling a journal changes no task links.
        surviving = await async_connection.execute(
            text("SELECT due_journal_id FROM tasks WHERE id = :task_id"),
            {"task_id": task_id},
        )
        assert surviving.scalar() == journal_id


@pytest.mark.integration
class TestSeriesCancelledNullableLinkFields:
    async def test_link_without_external_event_id_is_marked_cancelled(
        self, async_connection: AsyncConnection
    ) -> None:
        """Links with a NULL external_event_id still get sync_status updated
        (the UPDATE keys on the link PK, not the nullable external id)."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_nullid",
                start=datetime.now(UTC) + timedelta(hours=6),
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        await async_connection.execute(
            text(
                "UPDATE journal_external_event_links SET external_event_id = NULL"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal_id},
        )

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["cancelled"] == 1
        link_status = await async_connection.execute(
            text(
                "SELECT sync_status FROM journal_external_event_links"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal_id},
        )
        assert link_status.scalar() == "cancelled"
        assert await event_state(async_connection, journal_id) == "cancelled"


@pytest.mark.integration
class TestSeriesCancelledPerItemSavepoints:
    async def test_failed_delete_rolls_back_link_removal_for_that_item_only(
        self, async_connection: AsyncConnection
    ) -> None:
        """If delete_journal fails after the item's links were removed, the
        SAVEPOINT restores them; other items still process."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        journals: dict[str, int] = {}
        for key in ("fails", "succeeds"):
            created = await processor.process_event(
                sync_event(
                    "journal_event.created",
                    calendar_id=calendar_id,
                    external_event_id=f"{MASTER_ID}_{key}",
                    recurring_event_id=MASTER_ID,
                )
            )
            journals[key] = created["journal_id"]

        original_delete = processor.journal_service.delete_journal

        async def failing_delete(journal_id: int, *args: Any, **kwargs: Any) -> None:
            if journal_id == journals["fails"]:
                raise RuntimeError("simulated delete failure")
            return await original_delete(journal_id, *args, **kwargs)

        with (
            patch.object(
                processor.journal_service,
                "delete_journal",
                new=failing_delete,
            ),
            pytest.raises(JournalOutboxEventProcessingError, match="1 of 2"),
        ):
            await processor.process_event(series_cancelled_event(calendar_id))

        # The failed journal survives WITH its link row (the savepoint rolled
        # back the link deletion that ran before the failure).
        assert await journal_exists(async_connection, journals["fails"])
        link_count = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM journal_external_event_links"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": journals["fails"]},
        )
        assert link_count.scalar() == 1
        # The other journal was still deleted.
        assert not await journal_exists(async_connection, journals["succeeds"])


@pytest.mark.integration
class TestUnchangedEtagBackfillIntegration:
    async def test_unchanged_etag_update_backfills_link_and_series(
        self, async_connection: AsyncConnection
    ) -> None:
        """The worker's backfill promotion re-sends the SAME etag; the
        recurring id and series membership must persist anyway (otherwise the
        promotion loops forever)."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        external_event_id = f"{MASTER_ID}_20260801T090000Z"

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
            )
        )
        journal_id = created["journal_id"]
        assert await link_recurring_id(async_connection, journal_id) is None

        result = await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                etag='"etag-1"',  # unchanged — same as the create
                recurring_event_id=MASTER_ID,
            )
        )

        assert result["status"] == "skipped"
        assert await link_recurring_id(async_connection, journal_id) == MASTER_ID
        series_repo = SqlJournalSeriesRepository(async_connection)
        series = await series_repo.get_series_for_journal(journal_id, USER_ID)
        assert len(series) == 1
        assert series[0].recurring_event_id == MASTER_ID


@pytest.mark.integration
class TestPrefixFallbackScoping:
    async def test_prefix_fallback_skips_successor_and_backfilled_links(
        self, async_connection: AsyncConnection
    ) -> None:
        """The prefix fallback only matches unbackfilled links whose suffix is
        a single instance timestamp — successor-series ids (extra underscore
        segment) and links backfilled to another master are untouched."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        legacy = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260801T090000Z",
            )
        )
        successor_form = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_R20260901T090000_20260908T090000Z",
            )
        )
        backfilled_other = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20261001T090000Z",
                recurring_event_id=f"{MASTER_ID}_R20260901T090000",
            )
        )

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["deleted"] == 1
        assert not await journal_exists(async_connection, legacy["journal_id"])
        assert await journal_exists(async_connection, successor_form["journal_id"])
        assert (
            await event_state(async_connection, successor_form["journal_id"])
            != "cancelled"
        )
        assert await journal_exists(async_connection, backfilled_other["journal_id"])


@pytest.mark.integration
class TestDeletionGuardUserData:
    async def test_instance_with_route_falls_back_to_cancel(
        self, async_connection: AsyncConnection
    ) -> None:
        """A user-attached GPS route protects a far-future instance."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_routed",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        await async_connection.execute(
            text(
                "INSERT INTO routes (journal_id, name)"
                " VALUES (:journal_id, 'Planned track')"
            ),
            {"journal_id": journal_id},
        )

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"

    async def test_instance_with_type_data_falls_back_to_cancel(
        self, async_connection: AsyncConnection
    ) -> None:
        """User-added type data (e.g. mood) protects a far-future instance."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_mooded",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        await async_connection.execute(
            text(
                "INSERT INTO journal_mood_data (journal_id, mood_value)"
                " VALUES (:journal_id, 4)"
            ),
            {"journal_id": journal_id},
        )

        result = await processor.process_event(series_cancelled_event(calendar_id))

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"


@pytest.mark.integration
class TestStickyCancellationOnRedelivery:
    async def test_edited_journal_survives_repeated_series_cancellation(
        self, async_connection: AsyncConnection
    ) -> None:
        """Marking a journal cancelled bumps the link timestamp and erases the
        edit signal; a redelivered/repeated series_cancelled event must not
        delete the previously-protected journal."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_sticky",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]

        # Local edit -> protected on the first pass.
        await async_connection.execute(
            text(
                "UPDATE journals SET content = 'my notes', updated_at = :ts"
                " WHERE id = :id"
            ),
            {"ts": datetime.now(UTC) + timedelta(seconds=30), "id": journal_id},
        )

        first = await processor.process_event(series_cancelled_event(calendar_id))
        assert first["cancelled"] == 1
        assert first["deleted"] == 0

        # Redelivery / repeated upstream cancellation: the link timestamp was
        # bumped by the first pass, so the edit signal is gone — the sticky
        # cancelled status must protect the journal instead.
        second = await processor.process_event(series_cancelled_event(calendar_id))

        assert second["deleted"] == 0
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"
