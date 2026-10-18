"""Journal writes lock in a mode that queues writers but not task links.

Every journal write takes the journal's lock up front - unconditional ones too,
since an unconditional read-modify-write races as well. The mode matters:

- a task link or retarget holds ``FOR KEY SHARE`` on the journal it anchors
  to, and the rule in ``JournalRepository.find_and_lock_by_ids_for_user`` is
  that an ordinary journal edit **never waits behind it**. ``FOR UPDATE``
  would; ``FOR NO KEY UPDATE`` - the mode a plain ``UPDATE`` of the row takes
  anyway - does not;
- two journal writers must still queue, or the lock serialises nothing.

Run against real PostgreSQL on two committed connections, because lock modes
are a property of the lock manager, not of the code's shape.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_touch import lock_journal
from app.core.journal.services.journal_write_guard import guard_journal_write
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    wait_until_blocked_on_a_lock,
)
from tests.integration.journal.committed_journal import committed_journal


@pytest.fixture
async def journal(async_engine: AsyncEngine) -> AsyncIterator[tuple[str, int]]:
    async with committed_journal(async_engine) as committed:
        yield committed


@pytest.mark.integration
class TestJournalWriteLockMode:
    async def test_a_journal_write_does_not_wait_behind_a_task_link(
        self, async_engine: AsyncEngine, journal: tuple[str, int]
    ) -> None:
        user_id, journal_id = journal
        async with async_engine.connect() as linking, async_engine.connect() as writing:
            async with unit_of_work(linking):
                await SqlJournalRepository(linking).find_and_lock_by_ids_for_user(
                    user_id, [journal_id]
                )

                async with unit_of_work(writing):
                    await bounded(
                        guard_journal_write(
                            SqlJournalRepository(writing), journal_id, None
                        ),
                        timeout=5,
                    )
                    await bounded(lock_journal(writing, journal_id), timeout=5)

    async def test_two_journal_writes_queue(
        self, async_engine: AsyncEngine, journal: tuple[str, int]
    ) -> None:
        _, journal_id = journal
        async with async_engine.connect() as first, async_engine.connect() as second:

            async def second_write() -> None:
                async with unit_of_work(second):
                    await guard_journal_write(
                        SqlJournalRepository(second), journal_id, None
                    )

            second_pid = await backend_pid(second)
            async with unit_of_work(first):
                await lock_journal(first, journal_id)
                queued = asyncio.create_task(second_write())
                await wait_until_blocked_on_a_lock(async_engine, second_pid)
                assert not queued.done()
            await bounded(queued)
