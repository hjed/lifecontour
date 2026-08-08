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

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import TaskStatus
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.di.contacts import ContactProvider
from app.infrastructure.di.infrastructure import InfrastructureProvider
from app.infrastructure.di.integrations import IntegrationProvider
from app.infrastructure.di.journal import JournalProvider
from app.infrastructure.di.settings import SettingsProvider
from app.infrastructure.di.tasks import TaskProvider
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

USER_ID = "test-user-123"
# A second, unrelated owner. Owner scoping is only worth asserting against real
# rows belonging to someone else, never against a merely absent id.
OTHER_USER_ID = "other-user-456"

COUNT_TASKS = "SELECT COUNT(*) FROM tasks WHERE user_id = :user_id"
COUNT_CONTACT_LINKS = "SELECT COUNT(*) FROM task_contacts"
COUNT_CONTACT_LINKS_FOR_TASK = (
    "SELECT COUNT(*) FROM task_contacts WHERE task_id = :task_id"
)
COUNT_INTERMEDIATE_JOURNALS = "SELECT COUNT(*) FROM task_intermediate_journals"

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
_INSERT_CONTACT_LINK = text("""
    INSERT INTO task_contacts (task_id, contact_id)
    VALUES (:task_id, :contact_id)
""")
_DELETE_CONTACT = text("DELETE FROM contacts WHERE id = :contact_id")
_SELECT_CONTACT_LINKS = text(
    "SELECT contact_id FROM task_contacts WHERE task_id = :task_id ORDER BY contact_id"
)

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


async def link_contact(conn: AsyncConnection, *, task_id: int, contact_id: int) -> None:
    """Link a contact to a task by inserting the row directly.

    Used to establish a *starting position* — a task that already has a link —
    without driving the surface under test through it, which would make the
    arrangement part of what is being asserted.
    """
    await conn.execute(
        _INSERT_CONTACT_LINK, {"task_id": task_id, "contact_id": contact_id}
    )


async def linked_contact_ids(conn: AsyncConnection, task_id: int) -> list[int]:
    """The contact ids linked to ``task_id``, read straight from the table."""
    result = await conn.execute(_SELECT_CONTACT_LINKS, {"task_id": task_id})
    return [int(row[0]) for row in result.fetchall()]


async def delete_contact(conn: AsyncConnection, contact_id: int) -> None:
    """Delete a contact row, letting the schema's cascades do whatever they do."""
    await conn.execute(_DELETE_CONTACT, {"contact_id": contact_id})


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


@dataclass(frozen=True)
class TaskEventRow:
    """One ``outbox_events`` row published by the tasks domain, decoded."""

    event_id: str
    event_type: str
    aggregate_id: int
    payload: dict[str, Any]
    occurred_at: datetime


# Matched on the type prefix rather than an enumerated list, so the phases that
# add the remaining seven event types inherit these assertions instead of having
# to remember to widen a tuple. No other domain's event type begins "Task".
_SELECT_TASK_EVENTS = text("""
    SELECT event_id, event_type, aggregate_id, event_data, occurred_at
    FROM outbox_events
    WHERE event_type LIKE 'Task%'
    ORDER BY occurred_at, id
""")


async def task_events(
    conn: AsyncConnection, *, task_id: int | None = None
) -> list[TaskEventRow]:
    """Every task domain event in the outbox, oldest first.

    Read straight from the table rather than through the publisher, for the same
    reason the link helpers bypass the repository: a test asserting the service
    wrote a row should not read it back through the port it wrote through.

    ``event_data`` is decoded here because the column is ``TEXT`` — the payload
    reaches its consumers as JSON, and a test that compared Python objects would
    not be testing what the projection will actually see.
    """
    rows = await conn.execute(_SELECT_TASK_EVENTS)
    events = [
        TaskEventRow(
            event_id=str(row.event_id),
            event_type=str(row.event_type),
            aggregate_id=int(row.aggregate_id),
            payload=json.loads(row.event_data),
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]
    if task_id is None:
        return events
    return [event for event in events if event.aggregate_id == task_id]


async def stored_status(conn: AsyncConnection, task_id: int) -> str:
    """The status column as the database holds it, bypassing every layer above."""
    return str(
        (
            await conn.execute(
                text("SELECT status FROM tasks WHERE id = :task_id"),
                {"task_id": task_id},
            )
        ).scalar_one()
    )


async def stored_text(conn: AsyncConnection, task_id: int) -> str:
    """The text column as the database holds it, bypassing every layer above."""
    return str(
        (
            await conn.execute(
                text("SELECT text FROM tasks WHERE id = :task_id"),
                {"task_id": task_id},
            )
        ).scalar_one()
    )


async def backdate_updated_at(conn: AsyncConnection, task_id: int) -> datetime:
    """Move a task's ``updated_at`` into the past, and return where it was put.

    **A no-op test needs this to mean anything.** PostgreSQL's ``now()`` is
    ``transaction_timestamp()`` — constant for a whole transaction — and the
    integration fixture runs each test inside one. So the ``DEFAULT now()`` the
    seed row was inserted with and the ``updated_at = now()`` an update writes
    are the *identical* value, and "``updated_at`` did not move" holds whether
    or not a write happened. Review caught exactly that: the assertion passed
    against a service with the no-op short-circuit deleted.

    Backdating breaks the tie. The stored timestamp is now something ``now()``
    cannot produce, so a write that did happen is visible as a change and a
    write that did not is visible as this value surviving.
    """
    moved_to = FIXED_PAST_INSTANT
    await conn.execute(
        text("UPDATE tasks SET updated_at = :moved_to WHERE id = :task_id"),
        {"moved_to": moved_to, "task_id": task_id},
    )
    return moved_to


async def task_exists(conn: AsyncConnection, task_id: int) -> bool:
    """Whether a task row is still there at all.

    Distinct from ``stored_status`` and ``stored_text``, which both assume the
    row exists and raise if it does not: a deletion test needs to ask the
    question rather than trip over the answer.
    """
    return (
        await conn.execute(
            text("SELECT 1 FROM tasks WHERE id = :task_id"), {"task_id": task_id}
        )
    ).scalar_one_or_none() is not None


async def stored_anchors(conn: AsyncConnection, task_id: int) -> tuple[int, int]:
    """The task's two anchor columns as ``(creating, due)``, straight from the row.

    Read from the database rather than from a returned entity, so a test can
    tell a persisted anchor change from one that only exists in memory — and,
    for the creating anchor, prove that nothing wrote to it at all. The same
    read serves the other direction: an assertion that a task was *not* touched
    by somebody else's cascade covers the columns that cascade could plausibly
    have reached, rather than only the row's continued existence.
    """
    row = (
        await conn.execute(
            text(
                "SELECT creating_journal_id, due_journal_id "
                "FROM tasks WHERE id = :task_id"
            ),
            {"task_id": task_id},
        )
    ).one()
    return int(row.creating_journal_id), int(row.due_journal_id)


async def intermediate_journal_ids(conn: AsyncConnection, task_id: int) -> list[int]:
    """The task's intermediate-journal links, oldest first, straight from the table.

    The repository has a method for this, but a test asserting that the *service*
    wrote a link should not read it back through the same port it wrote through.
    """
    rows = await conn.execute(
        text(
            "SELECT journal_id FROM task_intermediate_journals "
            "WHERE task_id = :task_id ORDER BY created_at, journal_id"
        ),
        {"task_id": task_id},
    )
    return [int(row.journal_id) for row in rows]


def service_on(
    connection: AsyncConnection,
    user_settings_repository: SqlUserSettingsRepository,
    repo: type[SqlTaskRepository] = SqlTaskRepository,
) -> TaskService:
    """A ``TaskService`` over real adapters on ``connection``.

    The ``service`` fixture is bound to the test's single savepoint connection;
    the concurrency tests need one service per real connection, which is the
    only way two units of work can overlap. ``repo`` lets a test substitute a
    repository subclass that observes or signals from inside the call.
    """
    return TaskService(
        task_repo=repo(connection),
        journal_repo=SqlJournalRepository(connection),
        contact_repo=SqlContactRepository(connection),
        date_resolver=JournalDateResolver(user_settings_repo=user_settings_repository),
        event_publisher=OutboxEventPublisher(connection),
    )


@asynccontextmanager
async def committed_task(
    async_engine: AsyncEngine,
    *,
    journal_offsets: Sequence[int] = (7,),
    status: TaskStatus = TaskStatus.NOT_DONE,
) -> AsyncIterator[tuple[str, int, list[int]]]:
    """A task that really is committed, under an owner nobody else will see.

    The concurrency tests need two connections to see the same row, which the
    savepoint fixture cannot give them: its outer transaction is invisible to
    everyone else and is rolled back at teardown. So these rows are committed
    for real, scoped to a one-off user id, and deleted again whatever happens.

    ``journal_offsets`` says how many journals to create and where to put them
    relative to now; the task is anchored to the first one as both its creating
    and its due journal, and the rest are there for a test that needs somewhere
    to retarget *to*.

    Yields:
        ``(user_id, task_id, journal_ids)``.
    """
    user_id = f"race-{uuid4()}"
    async with async_engine.connect() as setup:
        journal_ids = [
            await create_journal(
                SqlJournalRepository(setup),
                title=f"Journal at {offset:+d}d",
                days_offset=offset,
                user_id=user_id,
            )
            for offset in journal_offsets
        ]
        task_id = await create_task(
            setup,
            creating_journal_id=journal_ids[0],
            due_journal_id=journal_ids[0],
            status=status,
            user_id=user_id,
        )
        await setup.commit()

    try:
        yield user_id, task_id, journal_ids
    finally:
        async with async_engine.connect() as cleanup:
            # The link rows cascade with the task, so the two deletes below are
            # the whole of the clean-up.
            await cleanup.execute(
                text("DELETE FROM tasks WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            await cleanup.execute(
                text("DELETE FROM journals WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            await cleanup.commit()


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
