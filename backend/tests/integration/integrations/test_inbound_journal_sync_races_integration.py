"""Inbound calendar syncs overlapping local journal writes, against real PostgreSQL.

Issue #1813, the journal twin of #1735: the inbound ``journal_event.updated``
path read the stored journal without its lock, merged the inbound fields with
protection against that read, and saved a whole journal built from it - so a
local title edit committed in between was reverted, and the protection check,
comparing the stale read's ``updated_at``, could not see it.

Every row here is committed for real under a one-off owner (two connections
cannot share the savepoint fixture) and deleted afterwards, events included:
the services run on real connections, so what they publish is committed too.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from core_shared.models.journals import JournalNotFoundError
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_patch import JournalPatch
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    overlap,
)
from tests.integration.core.integrations.journal_sync_seeding import (
    build_processor,
    create_calendar,
    sync_event,
)
from tests.integration.journal.committed_journal import journal_service_on

EXTERNAL_EVENT_ID = "race-event"
START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
MOVED_START = START + timedelta(hours=2)


@dataclass(frozen=True)
class Synced:
    user_id: str
    calendar_id: str
    journal_id: int
    other_journal_id: int


async def _process(connection: AsyncConnection, event: OutboxEvent) -> dict[str, Any]:
    """Process an event as the stream consumer does: one unit of work."""
    async with unit_of_work(connection):
        return await build_processor(connection).process_event(event)


@asynccontextmanager
async def synced_journals(async_engine: AsyncEngine) -> AsyncIterator[Synced]:
    """A journal imported from Google, and a second one to merge it into.

    The second is imported from another event in the same calendar, so a merge
    into it keeps the first's event as a merged alias rather than its link.
    """
    user_id = f"race-{uuid4()}"
    async with async_engine.connect() as setup:
        calendar_id = await create_calendar(setup, user_id=user_id)
        # A Google calendar, so a merge counts its events as inbound records.
        await setup.execute(
            text("UPDATE calendars SET google_calendar_id = :g WHERE id = :id"),
            {"g": f"{user_id}@group.calendar.google.com", "id": calendar_id},
        )
        await setup.commit()
    journal_ids: list[int] = []
    try:
        async with async_engine.connect() as setup:
            for external_event_id, title in (
                (EXTERNAL_EVENT_ID, "Physio appointment"),
                ("race-other-event", "Physio (duplicate)"),
            ):
                created = await _process(
                    setup,
                    sync_event(
                        "journal_event.created",
                        calendar_id=calendar_id,
                        external_event_id=external_event_id,
                        user_id=user_id,
                        title=title,
                        start=START,
                    ),
                )
                journal_ids.append(int(created["journal_id"]))
        yield Synced(user_id, calendar_id, journal_ids[0], journal_ids[1])
    finally:
        async with async_engine.connect() as cleanup:
            for statement in (
                "DELETE FROM outbox_events WHERE aggregate_id = ANY(:ids)",
                "DELETE FROM journals WHERE user_id = :u",
                "DELETE FROM calendars WHERE user_id = :u",
            ):
                await cleanup.execute(
                    text(statement),
                    {"ids": journal_ids, "u": user_id},
                )
            await cleanup.commit()


def _google_update(synced: Synced) -> OutboxEvent:
    """Google renamed the event and moved it two hours later."""
    return sync_event(
        "journal_event.updated",
        calendar_id=synced.calendar_id,
        external_event_id=EXTERNAL_EVENT_ID,
        user_id=synced.user_id,
        title="Physio (rescheduled)",
        start=MOVED_START,
        etag='"etag-2"',
        existing_journal_id=synced.journal_id,
    )


async def _retitle_locally(connection: AsyncConnection, journal_id: int) -> None:
    await journal_service_on(connection).patch_journal(
        journal_id, JournalPatch(title="Local title"), connection
    )


async def _stored(async_engine: AsyncEngine, journal_id: int) -> Any:
    async with async_engine.connect() as check:
        return await SqlJournalRepository(check).find_by_id(journal_id)


@pytest.mark.integration
class TestInboundJournalSyncOverlappingALocalEdit:
    async def test_a_local_edit_committed_first_is_not_reverted(
        self, async_engine: AsyncEngine
    ) -> None:
        async with synced_journals(async_engine) as synced:

            async def local_edit(connection: AsyncConnection) -> None:
                await _retitle_locally(connection, synced.journal_id)

            async def inbound(connection: AsyncConnection) -> None:
                await _process(connection, _google_update(synced))

            await overlap(async_engine, local_edit, inbound)

            stored = await _stored(async_engine, synced.journal_id)
            assert stored.title == "Local title"
            assert stored.event_date_range.start == MOVED_START

    async def test_a_local_edit_made_during_an_inbound_update_lands_after_it(
        self, async_engine: AsyncEngine
    ) -> None:
        async with synced_journals(async_engine) as synced:

            async def inbound(connection: AsyncConnection) -> None:
                await _process(connection, _google_update(synced))

            async def local_edit(connection: AsyncConnection) -> None:
                await _retitle_locally(connection, synced.journal_id)

            await overlap(async_engine, inbound, local_edit)

            stored = await _stored(async_engine, synced.journal_id)
            assert stored.title == "Local title"
            assert stored.event_date_range.start == MOVED_START


@pytest.mark.integration
class TestInboundJournalSyncOverlappingAMerge:
    async def test_an_update_for_a_journal_merged_away_meanwhile_is_retried(
        self, async_engine: AsyncEngine
    ) -> None:
        """The merge goes first; the update finds its journal gone.

        It must fail - redelivered, it finds the event kept as a merged alias
        and skips - never write the survivor from its stale read.
        """
        async with synced_journals(async_engine) as synced:

            async def merge(connection: AsyncConnection) -> None:
                publisher = OutboxEventPublisher(connection)
                await JournalMergeService(
                    journal_repo=SqlJournalRepository(connection),
                    event_publisher=publisher,
                    task_merge_service=TaskJournalMergeService(
                        task_anchor_repo=SqlTaskAnchorRepository(connection),
                        event_publisher=publisher,
                    ),
                ).merge_journals(
                    synced.other_journal_id, synced.journal_id, transaction=connection
                )

            async def inbound(connection: AsyncConnection) -> None:
                with pytest.raises(JournalNotFoundError):
                    await _process(connection, _google_update(synced))

            await overlap(async_engine, merge, inbound)

            async with async_engine.connect() as redelivery:
                result = await _process(redelivery, _google_update(synced))

            assert (result["status"], result["reason"]) == ("skipped", "merged_alias")
            assert result["journal_id"] == synced.other_journal_id
            survivor = await _stored(async_engine, synced.other_journal_id)
            assert survivor.event_date_range.start == START
