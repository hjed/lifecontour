"""Associating a list queues at the journal, before it takes the list.

A journal delete and a journal merge hold the journal ``FOR UPDATE`` and only
then write the lists associated with it. An association therefore takes the
journal first (``FOR KEY SHARE``, which waits behind ``FOR UPDATE``) and the list
second: were it the other way round, it could hold the list the delete is about
to write while waiting for the journal the delete holds.

Staged on real connections: one holds the journal as a delete or merge would,
the association is started and seen to wait, and a third connection proves the
list row is still free while it does. Committed rows belong to a one-off owner
and are removed afterwards, lists before journals.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from core_shared.models.tasks import TaskList, TaskListJournalNotFoundError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    settle,
    wait_until_blocked_on_a_lock,
)
from tests.integration.tasks.task_seeding import create_journal, seed_task_list
from tests.task_list_service_factory import build_task_list_service

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_HOLD_JOURNAL = text("SELECT id FROM journals WHERE id = :id FOR UPDATE")
_DELETE_JOURNAL = text("DELETE FROM journals WHERE id = :id")
_TAKE_LIST_NOWAIT = text(
    "SELECT id FROM task_lists WHERE id = :id FOR NO KEY UPDATE NOWAIT"
)
_ASSOCIATED = text("SELECT associated_journal_id FROM task_lists WHERE id = :id")


@pytest.fixture
async def racing_owner(async_engine: AsyncEngine) -> AsyncIterator[str]:
    """A one-off owner whose committed rows are deleted after the test."""
    owner = f"race-{uuid4()}"
    yield owner
    async with async_engine.connect() as cleanup:
        await cleanup.execute(
            text(
                "DELETE FROM outbox_events"
                " WHERE event_data::jsonb ->> 'user_id' = :owner"
            ),
            {"owner": owner},
        )
        for table in ("task_lists", "journals"):
            await cleanup.execute(
                text(f"DELETE FROM {table} WHERE user_id = :owner"),
                {"owner": owner},
            )
        await cleanup.commit()


async def _committed_journal_and_list(
    async_engine: AsyncEngine, owner: str
) -> tuple[int, int]:
    async with async_engine.connect() as conn:
        journal_id = await create_journal(
            SqlJournalRepository(conn), title="Trip", user_id=owner
        )
        task_list = await seed_task_list(conn, "Packing", user_id=owner)
        assert task_list.id is not None
        await conn.commit()
    return journal_id, task_list.id


async def _associate(
    connection: AsyncConnection, owner: str, task_list_id: int, journal_id: int
) -> TaskList:
    async with unit_of_work(connection):
        return await build_task_list_service(connection).update_task_list(
            user_id=owner,
            task_list_id=task_list_id,
            patch=TaskListPatch(associated_journal_id=journal_id),
            transaction=connection,
        )


async def _list_is_free(async_engine: AsyncEngine, task_list_id: int) -> None:
    """Take the list row without waiting, which fails if anyone holds it."""
    async with async_engine.connect() as probe:
        await probe.execute(_TAKE_LIST_NOWAIT, {"id": task_list_id})
        await probe.rollback()


async def _stored_association(async_engine: AsyncEngine, task_list_id: int) -> object:
    async with async_engine.connect() as reader:
        stored = (await reader.execute(_ASSOCIATED, {"id": task_list_id})).scalar_one()
        await reader.rollback()
    return stored


class TestAnAssociationWaitsForTheJournalFirst:
    async def test_a_journal_deleted_meanwhile_is_refused_and_the_list_left_alone(
        self, async_engine: AsyncEngine, racing_owner: str
    ) -> None:
        journal_id, list_id = await _committed_journal_and_list(
            async_engine, racing_owner
        )

        async with (
            async_engine.connect() as deleting,
            async_engine.connect() as associating,
        ):
            pid = await backend_pid(associating)
            pending: asyncio.Task[TaskList] | None = None
            try:
                await deleting.execute(_HOLD_JOURNAL, {"id": journal_id})
                pending = asyncio.create_task(
                    _associate(associating, racing_owner, list_id, journal_id)
                )
                await wait_until_blocked_on_a_lock(async_engine, pid)

                await _list_is_free(async_engine, list_id)

                await deleting.execute(_DELETE_JOURNAL, {"id": journal_id})
                await deleting.commit()

                with pytest.raises(TaskListJournalNotFoundError):
                    await bounded(pending)
            finally:
                await settle(pending)

        assert await _stored_association(async_engine, list_id) is None

    async def test_a_journal_kept_meanwhile_is_associated_once_it_is_released(
        self, async_engine: AsyncEngine, racing_owner: str
    ) -> None:
        journal_id, list_id = await _committed_journal_and_list(
            async_engine, racing_owner
        )

        async with (
            async_engine.connect() as holding,
            async_engine.connect() as associating,
        ):
            pid = await backend_pid(associating)
            pending: asyncio.Task[TaskList] | None = None
            try:
                await holding.execute(_HOLD_JOURNAL, {"id": journal_id})
                pending = asyncio.create_task(
                    _associate(associating, racing_owner, list_id, journal_id)
                )
                await wait_until_blocked_on_a_lock(async_engine, pid)

                await _list_is_free(async_engine, list_id)

                await holding.commit()
                associated = await bounded(pending)
            finally:
                await settle(pending)

        assert associated.associated_journal_id == journal_id
        assert await _stored_association(async_engine, list_id) == journal_id
