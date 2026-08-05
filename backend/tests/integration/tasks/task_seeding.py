"""Shared seeding helpers for the task integration tests.

Both the constraint tests and the repository tests need the same three things —
a journal to anchor to, a contact to link, and a row count to assert against —
so they live here rather than being copied per file.

Journals are created through ``SqlJournalRepository`` so the anchors are real
journal rows; contacts are inserted directly because the contact domain's own
creation path is irrelevant to what these tests assert.
"""

from datetime import UTC, datetime, timedelta

from core_shared.models.journals import EventDateRange, Journal
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.infrastructure.di.contacts import ContactProvider
from app.infrastructure.di.infrastructure import InfrastructureProvider
from app.infrastructure.di.integrations import IntegrationProvider
from app.infrastructure.di.journal import JournalProvider
from app.infrastructure.di.settings import SettingsProvider
from app.infrastructure.di.tasks import TaskProvider

USER_ID = "test-user-123"
# A second, unrelated owner. Owner scoping is only worth asserting against real
# rows belonging to someone else, never against a merely absent id.
OTHER_USER_ID = "other-user-456"


async def create_journal(
    journal_repository: SqlJournalRepository,
    *,
    title: str = "Anchor Journal",
    days_offset: int = 0,
    start: datetime | None = None,
    user_id: str = USER_ID,
) -> int:
    """Create a journal and return its id.

    ``days_offset`` places the journal relative to the real clock, which is what
    a test asserting "a future journal is accepted" wants. Pass ``start``
    instead when the assertion is about a *date*: a date cannot be anchored on a
    moving instant, so the timezone-boundary tests fix theirs.
    """
    start = (
        start if start is not None else datetime.now(UTC) + timedelta(days=days_offset)
    )
    journal = await journal_repository.save(
        Journal(
            user_id=user_id,
            title=title,
            content="content",
            event_date_range=EventDateRange(
                start=start, end=start + timedelta(hours=1)
            ),
        )
    )
    assert journal.id is not None
    return journal.id


async def create_contact(conn: AsyncConnection, *, first_name: str = "Sarah") -> int:
    """Create a contact and return its id."""
    contact_id = (
        await conn.execute(
            text("INSERT INTO contacts (first_name) VALUES (:first_name) RETURNING id"),
            {"first_name": first_name},
        )
    ).scalar_one()
    return int(contact_id)


async def count(conn: AsyncConnection, sql: str, params: dict[str, int | str]) -> int:
    """Run a counting query and return the count."""
    return int((await conn.execute(text(sql), params)).scalar_one())


def make_task_container(connection: AsyncConnection) -> AsyncContainer:
    """A container that can resolve the whole tasks domain on ``connection``.

    ``TaskProvider`` no longer stands alone: ``TaskService`` reaches into the
    journal, contact and settings domains for the data its invariants need, and
    Dishka validates the *entire* graph at construction — so every provider those
    factories touch has to be present even when a test only asks for one object.
    ``InfrastructureProvider`` supplies ``Settings``, and ``IntegrationProvider``
    the sync-metadata repository ``ContactProvider``'s merge service wants.
    Neither is a dependency of anything the tasks domain resolves.
    """

    class _ConnectionProvider(Provider):
        def __init__(self, conn: AsyncConnection) -> None:
            super().__init__()
            self.conn = conn

        @provide(scope=Scope.REQUEST)
        def get_connection(self) -> AsyncConnection:
            return self.conn

    return make_async_container(
        _ConnectionProvider(connection),
        InfrastructureProvider(),
        ContactProvider(),
        IntegrationProvider(),
        JournalProvider(),
        SettingsProvider(),
        TaskProvider(),
    )
