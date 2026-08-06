"""Shared seeding helpers and fixtures for the task integration tests.

Every file that exercises task *creation* — the service, the endpoint and the
MCP tool — needs the same starting position: a journal to anchor to, a
future-dated journal to be due in, a contact to link, and a row count to assert
against. They live here rather than being copied per file.

Journals are created through ``SqlJournalRepository`` so the anchors are real
journal rows; contacts are inserted directly because the contact domain's own
creation path is irrelevant to what these tests assert.

The matching *fixtures* — ``journal_repository``, ``user_settings_repository``
and ``task_anchors`` — live in ``tests/integration/conftest.py`` instead. Their
consumers sit in three different directories (``tasks/``, ``api/``, ``mcp/``)
whose only shared conftest is that one, and pytest discovers fixtures by
inheritance; importing them into each module instead trips ruff's F811 at every
test that names one as a parameter.
"""

from datetime import UTC, datetime, timedelta

from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import TaskStatus
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

COUNT_TASKS = "SELECT COUNT(*) FROM tasks WHERE user_id = :user_id"
COUNT_CONTACT_LINKS = "SELECT COUNT(*) FROM task_contacts"

# Built here rather than inside the seeding functions, whose ``text`` keyword
# argument — the task's own text — would otherwise shadow ``sqlalchemy.text``.
_INSERT_TASK = text("""
    INSERT INTO tasks (user_id, text, status, creating_journal_id, due_journal_id)
    VALUES (:user_id, :text, :status, :creating_journal_id, :due_journal_id)
    RETURNING id
""")
_INSERT_INTERMEDIATE = text("""
    INSERT INTO task_intermediate_journals (task_id, journal_id)
    VALUES (:task_id, :journal_id)
""")

# Midday UTC on 1 January 2020 — long past in every timezone, and a *different
# local date* in the two zones the surface tests use: 02:00 on the 2nd in
# Kiritimati (+14), 01:00 on the 1st in Midway (-11). The pair is 25 hours
# apart, so no instant is ever the same date in both, which is what lets a
# timezone assertion be made without reading a clock.
FIXED_PAST_INSTANT = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)


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


async def create_task(
    conn: AsyncConnection,
    *,
    creating_journal_id: int,
    due_journal_id: int,
    text: str = "print the permit",
    status: TaskStatus = TaskStatus.NOT_DONE,
    user_id: str = USER_ID,
) -> int:
    """Insert a task directly and return its id.

    Deliberately not routed through ``TaskService``: the creation path can only
    produce a *not-done* task due in a *future* journal, and the anchor-integrity
    tests need the states a task reaches later in its life — done, cancelled, or
    due in a journal that has since passed. Those are legitimate rows the guard
    must still refuse to delete around, so they are seeded as rows.
    """
    task_id = (
        await conn.execute(
            _INSERT_TASK,
            {
                "user_id": user_id,
                "text": text,
                "status": status.value,
                "creating_journal_id": creating_journal_id,
                "due_journal_id": due_journal_id,
            },
        )
    ).scalar_one()
    return int(task_id)


async def link_intermediate_journal(
    conn: AsyncConnection, *, task_id: int, journal_id: int
) -> None:
    """Link a journal to a task as an intermediate journal."""
    await conn.execute(
        _INSERT_INTERMEDIATE, {"task_id": task_id, "journal_id": journal_id}
    )


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
