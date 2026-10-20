"""A journal that really is committed, for tests that overlap two connections."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.tasks.task_seeding import create_journal


@asynccontextmanager
async def committed_journal(
    async_engine: AsyncEngine,
) -> AsyncIterator[tuple[str, int]]:
    """A journal committed under an owner nobody else will see, deleted afterwards.

    Its events are deleted too: a service on a real connection commits them,
    and ``outbox_events`` has no owner to sweep them by - but journal ids are
    globally unique, so these are exactly this journal's.

    Yields:
        ``(user_id, journal_id)``.
    """
    user_id = f"race-{uuid4()}"
    async with async_engine.connect() as setup:
        journal_id = await create_journal(SqlJournalRepository(setup), user_id=user_id)
        await setup.commit()
    try:
        yield user_id, journal_id
    finally:
        async with async_engine.connect() as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM outbox_events "
                    "WHERE event_type LIKE 'Journal%' AND aggregate_id = :journal_id"
                ),
                {"journal_id": journal_id},
            )
            await cleanup.execute(
                text("DELETE FROM journals WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            await cleanup.commit()


def journal_service_on(connection: AsyncConnection) -> JournalService:
    """A ``JournalService`` over the real repositories on ``connection``."""
    return JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        task_anchor_repo=SqlTaskAnchorRepository(connection),
    )
