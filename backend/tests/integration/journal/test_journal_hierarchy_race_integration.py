"""Two overlapping re-parents cannot build a cycle between them.

Each write locks only its own journal, and validates the hierarchy by reading
the other journals - unlocked. So "A under B" and "B under A", started together,
each saw an acyclic tree and both committed: a cycle, which the recursive
depth and ancestry queries then walk forever. Hierarchy changes for one owner
now queue on a lock of their own, so the second validates against the first's
committed parent and is refused.

Run against real PostgreSQL on two committed connections; see
:mod:`tests.integration.concurrency_helpers`.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import uuid4

import pytest
from core_shared.models.journals import JournalCycleError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    settle,
    wait_until_blocked_on_a_lock,
)
from tests.integration.tasks.task_seeding import create_journal


def _service_on(connection: AsyncConnection) -> JournalService:
    return JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        task_anchor_repo=SqlTaskAnchorRepository(connection),
    )


@pytest.fixture
async def two_journals(async_engine: AsyncEngine) -> AsyncIterator[tuple[int, int]]:
    """Two top-level journals of one owner, committed and deleted afterwards."""
    user_id = f"race-{uuid4()}"
    async with async_engine.connect() as setup:
        repo = SqlJournalRepository(setup)
        ids = (
            await create_journal(repo, title="A", user_id=user_id),
            await create_journal(repo, title="B", user_id=user_id),
        )
        await setup.commit()
    try:
        yield ids
    finally:
        async with async_engine.connect() as cleanup:
            await cleanup.execute(
                text("DELETE FROM outbox_events WHERE aggregate_id = ANY(:ids)"),
                {"ids": list(ids)},
            )
            await cleanup.execute(
                text("UPDATE journals SET parent_id = NULL WHERE user_id = :u"),
                {"u": user_id},
            )
            await cleanup.execute(
                text("DELETE FROM journals WHERE user_id = :u"), {"u": user_id}
            )
            await cleanup.commit()


async def _reparent(connection: AsyncConnection, child: int, parent: int) -> None:
    service = _service_on(connection)
    stored = await service.journal_repo.find_by_id(child)
    assert stored is not None
    await service.update_journal(replace(stored, parent_id=parent), connection)


@pytest.mark.integration
async def test_two_overlapping_reparents_cannot_form_a_cycle(
    async_engine: AsyncEngine, two_journals: tuple[int, int]
) -> None:
    a, b = two_journals
    async with async_engine.connect() as first, async_engine.connect() as second:
        second_pid = await backend_pid(second)

        async def b_under_a() -> None:
            async with unit_of_work(second):
                await _reparent(second, b, a)

        overlapping: asyncio.Task[None] | None = None
        try:
            async with unit_of_work(first):
                await _reparent(first, a, b)
                overlapping = asyncio.create_task(b_under_a())
                await wait_until_blocked_on_a_lock(async_engine, second_pid)
            with pytest.raises(JournalCycleError):
                await bounded(overlapping)
        finally:
            await settle(overlapping)

    async with async_engine.connect() as check:
        parents = (
            await check.execute(
                text("SELECT id, parent_id FROM journals WHERE id = ANY(:ids)"),
                {"ids": [a, b]},
            )
        ).all()
    assert {row.id: row.parent_id for row in parents} == {a: b, b: None}
