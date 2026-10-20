"""Two journal writes overlapping against real PostgreSQL lose neither.

See :mod:`tests.integration.concurrency_helpers` for how the overlap is
arranged: the first write holds its transaction open until the second is
blocked on the journal's lock.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.journal.services.journal_patch import JournalPatch
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    wait_until_blocked_on_a_lock,
)
from tests.integration.journal.committed_journal import (
    committed_journal,
    journal_service_on,
)


@pytest.mark.integration
class TestOverlappingJournalWrites:
    async def test_a_partial_update_keeps_a_concurrent_change_it_did_not_name(
        self, async_engine: AsyncEngine
    ) -> None:
        """A retitle does not put back content written under it (#1557's journal twin).

        ``update_journal_entry`` and ``PATCH /journals/{id}`` used to copy every
        field they were not asked to change from a read of their own, and save
        the lot.
        """
        async with committed_journal(async_engine) as (_, journal_id):
            async with (
                async_engine.connect() as editing,
                async_engine.connect() as patching,
            ):

                async def retitle() -> None:
                    await journal_service_on(patching).patch_journal(
                        journal_id, JournalPatch(title="Retitled"), patching
                    )

                patching_pid = await backend_pid(patching)
                async with unit_of_work(editing):
                    await journal_service_on(editing).patch_journal(
                        journal_id, JournalPatch(content="Rewritten"), editing
                    )
                    overlapping = asyncio.create_task(retitle())
                    await wait_until_blocked_on_a_lock(async_engine, patching_pid)
                await bounded(overlapping)

            async with async_engine.connect() as check:
                stored = await journal_service_on(check).journal_repo.find_by_id(
                    journal_id
                )
            assert stored is not None
            assert (stored.title, stored.content) == ("Retitled", "Rewritten")
