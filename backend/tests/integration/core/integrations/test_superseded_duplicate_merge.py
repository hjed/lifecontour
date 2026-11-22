"""Integration tests for merging a re-keyed duplicate into its live sibling.

When both the old and the new instance sets of a re-timed recurrence were
journalled before the worker could adopt, the sweep finds an old link Google
no longer has on a day that already has a live journal of the same
recurrence. It sends the old id's cancellation carrying
``superseded_by_journal_id``, and the old journal is merged into that live one
- notes, tasks and contacts kept, the old id kept as a merged alias - rather
than left as a cancelled duplicate beside it.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
    create_calendar,
    event_state,
    journal_exists,
    sync_event,
)
from tests.integration.tasks.task_seeding import create_task

pytestmark = pytest.mark.integration

RECURRENCE = "dc7pp0jpb9fdfg6b6csu2jbfes"
OLD_START = (datetime.now(UTC) + timedelta(days=14)).replace(
    hour=3, minute=0, second=0, microsecond=0
)
NEW_START = OLD_START + timedelta(minutes=30)
OLD_ID = f"{RECURRENCE}_{OLD_START:%Y%m%dT%H%M%SZ}"
NEW_ID = f"{RECURRENCE}_{NEW_START:%Y%m%dT%H%M%SZ}"


async def _google_calendar(connection: AsyncConnection) -> str:
    """A Google-synced calendar: merges alias Google links only on one."""
    calendar_id = await create_calendar(connection)
    await connection.execute(
        text("""
            UPDATE calendars
            SET integration_source = 'google', google_calendar_id = 'work@example.com'
            WHERE id = :id
        """),
        {"id": calendar_id},
    )
    return calendar_id


async def _created(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    external_event_id: str,
    start: datetime,
    *,
    recurrence: str = RECURRENCE,
) -> int:
    result = await processor.process_event(
        sync_event(
            "journal_event.created",
            calendar_id=calendar_id,
            external_event_id=external_event_id,
            title="Retro",
            start=start,
            recurring_event_id=recurrence,
            series_recurring_event_id=recurrence,
        )
    )
    assert result["status"] == "success"
    journal_id: int = result["journal_id"]
    return journal_id


def _superseded_cancellation(
    calendar_id: str, journal_id: int, sibling_id: int
) -> OutboxEvent:
    event = sync_event(
        "journal_event.cancelled",
        calendar_id=calendar_id,
        external_event_id=OLD_ID,
        start=OLD_START,
        existing_journal_id=journal_id,
        recurring_event_id=RECURRENCE,
    )
    event.event_data["superseded_by_journal_id"] = sibling_id
    return event


async def _pair(
    connection: AsyncConnection,
) -> tuple[JournalOutboxEventProcessor, str, int, int]:
    calendar_id = await _google_calendar(connection)
    processor = build_processor(connection)
    old = await _created(processor, calendar_id, OLD_ID, OLD_START)
    sibling = await _created(processor, calendar_id, NEW_ID, NEW_START)
    return processor, calendar_id, old, sibling


async def _link_id(connection: AsyncConnection, journal_id: int) -> str | None:
    result = await connection.execute(
        text(
            "SELECT external_event_id FROM journal_external_event_links"
            " WHERE journal_id = :id"
        ),
        {"id": journal_id},
    )
    return result.scalar()


async def _alias_owner(connection: AsyncConnection, external_id: str) -> Any:
    result = await connection.execute(
        text(
            "SELECT journal_id FROM journal_merged_aliases"
            " WHERE user_id = :user_id AND external_id = :external_id"
        ),
        {"user_id": USER_ID, "external_id": external_id},
    )
    return result.scalar()


class TestSupersededDuplicateMerge:
    async def test_the_duplicate_is_merged_into_its_live_sibling(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor, calendar_id, old, sibling = await _pair(async_connection)
        await async_connection.execute(
            text("UPDATE journals SET content = 'my notes' WHERE id = :id"),
            {"id": old},
        )

        result = await processor.process_event(
            _superseded_cancellation(calendar_id, old, sibling)
        )

        assert result["status"] == "success"
        assert result["action"] == "merged"
        assert result["journal_id"] == sibling
        assert not await journal_exists(async_connection, old)
        assert await _link_id(async_connection, sibling) == NEW_ID
        assert await event_state(async_connection, sibling) == "confirmed"
        assert await _alias_owner(async_connection, OLD_ID) == sibling
        content = (
            await async_connection.execute(
                text("SELECT content FROM journals WHERE id = :id"), {"id": sibling}
            )
        ).scalar()
        assert "my notes" in (content or "")

    async def test_a_task_on_the_duplicate_moves_to_the_sibling(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor, calendar_id, old, sibling = await _pair(async_connection)
        task_id = await create_task(
            async_connection,
            creating_journal_id=old,
            due_journal_id=old,
            user_id=USER_ID,
        )

        await processor.process_event(
            _superseded_cancellation(calendar_id, old, sibling)
        )

        anchors = (
            await async_connection.execute(
                text(
                    "SELECT creating_journal_id, due_journal_id FROM tasks"
                    " WHERE id = :id"
                ),
                {"id": task_id},
            )
        ).one()
        assert tuple(anchors) == (sibling, sibling)

    @pytest.mark.parametrize(
        "spoil", ["gone", "cancelled", "other_recurrence", "itself"]
    )
    async def test_an_unusable_sibling_falls_back_to_cancelling(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
        spoil: str,
    ) -> None:
        processor, calendar_id, old, sibling = await _pair(async_connection)
        target = sibling
        if spoil == "gone":
            await async_connection.execute(
                text("DELETE FROM journals WHERE id = :id"), {"id": sibling}
            )
        elif spoil == "cancelled":
            await async_connection.execute(
                text(
                    "UPDATE journal_external_event_links SET sync_status = 'cancelled'"
                    " WHERE journal_id = :id"
                ),
                {"id": sibling},
            )
        elif spoil == "other_recurrence":
            await async_connection.execute(
                text(
                    "UPDATE journal_external_event_links"
                    " SET recurring_event_id = 'another-recurrence'"
                    " WHERE journal_id = :id"
                ),
                {"id": sibling},
            )
        else:
            target = old

        result = await processor.process_event(
            _superseded_cancellation(calendar_id, old, target)
        )

        assert result["status"] == "success"
        assert result.get("action") != "merged"
        assert await journal_exists(async_connection, old)
        assert await event_state(async_connection, old) == "cancelled"

    async def test_a_replay_after_the_merge_changes_nothing(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor, calendar_id, old, sibling = await _pair(async_connection)
        cancellation = _superseded_cancellation(calendar_id, old, sibling)
        await processor.process_event(cancellation)

        await processor.process_event(cancellation)

        assert not await journal_exists(async_connection, old)
        assert await event_state(async_connection, sibling) == "confirmed"
        assert await _link_id(async_connection, sibling) == NEW_ID

    async def test_a_past_duplicate_whose_merge_is_declined_is_left_alone(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The worker sends a merge even for a past journal; if the merge can
        no longer run, cancelling it instead would cancel an event that
        already happened."""
        calendar_id = await _google_calendar(async_connection)
        processor = build_processor(async_connection)
        past = datetime.now(UTC).replace(microsecond=0) - timedelta(days=30)
        old = await _created(processor, calendar_id, OLD_ID, past)
        sibling = await _created(
            processor, calendar_id, NEW_ID, past + timedelta(minutes=30)
        )
        await async_connection.execute(
            text("DELETE FROM journals WHERE id = :id"), {"id": sibling}
        )

        result = await processor.process_event(
            _superseded_cancellation(calendar_id, old, sibling)
        )

        assert result["status"] == "skipped"
        assert await event_state(async_connection, old) == "confirmed"

    async def test_private_notes_stay_private_in_the_merged_journal(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The duplicate's notes were never pushed to Google; folded into a
        journal that pushes its description, they would be on the next edit."""
        processor, calendar_id, old, sibling = await _pair(async_connection)
        await async_connection.execute(
            text(
                "UPDATE journal_calendar_info SET private_description = true"
                " WHERE journal_id = :id"
            ),
            {"id": old},
        )

        await processor.process_event(
            _superseded_cancellation(calendar_id, old, sibling)
        )

        private = (
            await async_connection.execute(
                text(
                    "SELECT private_description FROM journal_calendar_info"
                    " WHERE journal_id = :id"
                ),
                {"id": sibling},
            )
        ).scalar()
        assert private is True

    async def test_a_re_time_back_reclaims_an_id_the_merge_aliased(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Merged 14:00 into 14:30, then the organiser moves it back: Google
        re-issues the 14:00 ids, which the journal holds as merged aliases.
        The adoption takes the id back as the journal's link."""
        processor, calendar_id, old, sibling = await _pair(async_connection)
        await processor.process_event(
            _superseded_cancellation(calendar_id, old, sibling)
        )
        back = sync_event(
            "journal_event.updated",
            calendar_id=calendar_id,
            external_event_id=OLD_ID,
            title="Retro",
            start=OLD_START,
            etag='"etag-back"',
            existing_journal_id=sibling,
            recurring_event_id=RECURRENCE,
            series_recurring_event_id=RECURRENCE,
        )
        back.event_data["rekeyed_from"] = NEW_ID

        result = await processor.process_event(back)

        assert result["status"] == "success"
        assert await _link_id(async_connection, sibling) == OLD_ID
        assert await _alias_owner(async_connection, OLD_ID) is None
        journal_start = (
            await async_connection.execute(
                text("SELECT event_date_range_start FROM journals WHERE id = :id"),
                {"id": sibling},
            )
        ).scalar()
        assert journal_start == OLD_START


async def test_a_manual_merge_keeps_a_private_description_private(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """The same rule for any merge: either side private makes the result
    private, so no notes the user kept off Google are pushed there."""
    from core_shared.models.history import Provenance

    from app.core.journal.adapters.sql.journal_repository import (
        SqlJournalRepository,
    )
    from app.core.journal.services.journal_merge_service import JournalMergeService
    from app.core.tasks.adapters.sql.task_anchor_repository import (
        SqlTaskAnchorRepository,
    )
    from app.core.tasks.services.task_journal_merge_service import (
        TaskJournalMergeService,
    )
    from app.infrastructure.events.outbox_event_publisher import (
        OutboxEventPublisher,
    )

    _, _, old, sibling = await _pair(async_connection)
    await async_connection.execute(
        text(
            "UPDATE journal_calendar_info SET private_description = true"
            " WHERE journal_id = :id"
        ),
        {"id": old},
    )
    publisher = OutboxEventPublisher(async_connection)
    await JournalMergeService(
        SqlJournalRepository(async_connection),
        publisher,
        TaskJournalMergeService(
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
            event_publisher=publisher,
        ),
    ).merge_journals(
        target_id=sibling,
        source_id=old,
        transaction=async_connection,
        source=Provenance.UI,
        changed_by="ui",
    )

    private = (
        await async_connection.execute(
            text(
                "SELECT private_description FROM journal_calendar_info"
                " WHERE journal_id = :id"
            ),
            {"id": sibling},
        )
    ).scalar()
    assert private is True
