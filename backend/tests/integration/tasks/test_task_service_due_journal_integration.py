"""Integration tests for changing a task's due journal, against a real database.

``TaskService.update_task`` sets, changes and clears a list task's due journal
as a plain edit, and moves a journal-only task's under the retarget's rules.
The unit tests own the rules and their order. What only a real database shows:

- the stored anchors, the ``task_intermediate_journals`` row for the journal
  left, and the outbox events in write order, all in one transaction;
- a done list task staying done, its ``closed_at`` untouched;
- the read model's journal groups and tasks-due badge following the change;
- "today" judged on the timezone stored in ``user_settings``;
- a refusal leaving the row and the outbox untouched;
- a journal delete racing the change, in both journals' roles, ending cleanly.

The REST and MCP surfaces have their own suites, and the lock order against a
journal merge is pinned in ``test_retarget_merge_lock_order_integration.py``.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest
from core_shared.models.tasks import (
    TaskAnchorJournalNotFoundError,
    TaskDomainError,
    TaskDueJournalNotFutureError,
    TaskStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.shared.patch import UNSET, Unset
from tests.integration.concurrency_helpers import overlap
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    committed_task_list,
    create_journal,
    create_list_task,
    create_task,
    intermediate_journal_ids,
    seed_task_list_id,
    service_on,
    stored_closed_at,
    task_events,
)
from tests.journal_service_factory import build_journal_service

pytestmark = pytest.mark.integration

# 06:00 on 6 August in Sydney (+10); the 5th is still running in UTC.
SYDNEY_MORNING = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
# 19:00 in Sydney on the 6th: tomorrow in UTC, but already today in Sydney.
STARTS_SYDNEY_TODAY = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
# In the future in every zone at ``SYDNEY_MORNING``.
STARTS_IN_TWO_DAYS = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
STARTS_IN_A_WEEK = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
LATER = date(2026, 9, 1)


async def _anchors(conn: AsyncConnection, task_id: int) -> Any:
    return (
        await conn.execute(
            text("SELECT due_journal_id, due_date, status FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
    ).one()


async def _change(
    service: TaskService,
    conn: AsyncConnection,
    task_id: int,
    due_journal_id: int | None | Unset = UNSET,
    *,
    due_date: date | None | Unset = UNSET,
    status: TaskStatus | None = None,
    user_id: str = USER_ID,
) -> None:
    await service.update_task(
        user_id=user_id,
        task_id=task_id,
        due_journal_id=due_journal_id,
        due_date=due_date,
        status=status,
        transaction=conn,
        now=SYDNEY_MORNING,
    )


async def _two_journals(repo: SqlJournalRepository) -> tuple[int, int]:
    """Two future journals of the user's: the one a task leaves, and its next."""
    first = await create_journal(repo, title="Beach weekend", start=STARTS_IN_TWO_DAYS)
    second = await create_journal(repo, title="Hike", start=STARTS_IN_A_WEEK)
    return first, second


class TestAListTasksDueJournal:
    async def test_set_writes_the_journal_and_one_event(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _two_journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        await _change(service, async_connection, task_id, journal_id)

        assert (await _anchors(async_connection, task_id)).due_journal_id == journal_id
        assert await intermediate_journal_ids(async_connection, task_id) == []
        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"due_journal_id": [None, journal_id]}

    async def test_change_retains_the_journal_left_and_publishes_link_first(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        old_id, new_id = await _two_journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=old_id
        )

        await _change(service, async_connection, task_id, new_id)

        assert (await _anchors(async_connection, task_id)).due_journal_id == new_id
        assert await intermediate_journal_ids(async_connection, task_id) == [old_id]
        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == [
            "TaskJournalLinked",
            "TaskUpdated",
        ]
        assert events[0].payload["journal_id"] == old_id
        assert events[0].payload["origin"] == "retarget"
        assert events[1].payload["changed_fields"] == {
            "due_journal_id": [old_id, new_id]
        }

    async def test_clear_retains_the_journal_and_leaves_the_task_undated(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _two_journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=journal_id
        )

        await _change(service, async_connection, task_id, None)

        row = await _anchors(async_connection, task_id)
        assert (row.due_journal_id, row.due_date) == (None, None)
        assert await intermediate_journal_ids(async_connection, task_id) == [journal_id]
        events = await task_events(async_connection, task_id=task_id)
        assert events[-1].payload["changed_fields"] == {
            "due_journal_id": [journal_id, None]
        }

    async def test_a_done_task_stays_done_and_keeps_its_closed_at(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        old_id, new_id = await _two_journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            due_journal_id=old_id,
            status=TaskStatus.DONE,
        )
        closed_at = await stored_closed_at(async_connection, task_id)
        assert closed_at is not None

        await _change(service, async_connection, task_id, new_id)

        row = await _anchors(async_connection, task_id)
        assert (row.due_journal_id, row.status) == (new_id, TaskStatus.DONE.value)
        assert await stored_closed_at(async_connection, task_id) == closed_at

    async def test_a_journal_replaces_a_due_date(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _two_journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=LATER
        )

        await _change(service, async_connection, task_id, journal_id)

        row = await _anchors(async_connection, task_id)
        assert (row.due_journal_id, row.due_date) == (journal_id, None)
        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.payload["changed_fields"] == {
            "due_journal_id": [None, journal_id],
            "due_date": ["2026-09-01", None],
        }

    async def test_reads_back_due_in_the_new_journal_and_mentioned_in_the_old(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        old_id, new_id = await _two_journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=old_id
        )

        await _change(service, async_connection, task_id, new_id)

        left = await read_service.read_models_for_journal(
            USER_ID, old_id, now=SYDNEY_MORNING
        )
        joined = await read_service.read_models_for_journal(
            USER_ID, new_id, now=SYDNEY_MORNING
        )
        assert left.due == ()
        assert [model.task.id for model in left.mentioned] == [task_id]
        assert [model.task.id for model in joined.due] == [task_id]
        old_journal = await journal_repository.find_by_id(old_id)
        new_journal = await journal_repository.find_by_id(new_id)
        assert old_journal is not None
        assert new_journal is not None
        counts = await read_service.due_task_counts(
            USER_ID, [old_journal, new_journal], now=SYDNEY_MORNING
        )
        assert counts == {new_id: 1}


class TestAJournalOnlyTaskThroughTheUpdate:
    async def test_stores_what_a_retarget_stores(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Revived from cancelled, with one status change in the outbox."""
        old_id, new_id = await _two_journals(journal_repository)
        creating_id = await create_journal(journal_repository, title="Today")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=old_id,
            status=TaskStatus.CANCELLED,
        )

        await _change(
            service, async_connection, task_id, new_id, status=TaskStatus.NOT_DONE
        )

        row = await _anchors(async_connection, task_id)
        assert (row.due_journal_id, row.status) == (new_id, TaskStatus.NOT_DONE.value)
        assert await intermediate_journal_ids(async_connection, task_id) == [old_id]
        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == [
            "TaskJournalLinked",
            "TaskDueJournalRetargeted",
        ]
        assert events[1].payload["changed_fields"] == {
            "due_journal_id": [old_id, new_id],
            "status": ["cancelled", "not_done"],
        }


class TestRefusals:
    async def test_a_journal_dated_today_in_sydney_is_not_future(
        self,
        service: TaskService,
        user_settings_repository: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        journal_id = await create_journal(
            journal_repository, title="Tonight", start=STARTS_SYDNEY_TODAY
        )
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        with pytest.raises(TaskDueJournalNotFutureError):
            await _change(service, async_connection, task_id, journal_id)

        assert (await _anchors(async_connection, task_id)).due_journal_id is None
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_another_users_journal_is_not_found_and_nothing_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        theirs = await create_journal(
            journal_repository, start=STARTS_IN_TWO_DAYS, user_id=OTHER_USER_ID
        )
        mine, _ = await _two_journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=mine
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as raised:
            await _change(service, async_connection, task_id, theirs)

        assert raised.value.anchor == "due"
        assert (await _anchors(async_connection, task_id)).due_journal_id == mine
        assert await intermediate_journal_ids(async_connection, task_id) == []
        assert await task_events(async_connection, task_id=task_id) == []


# ---------------------------------------------------------------------------
# A journal delete racing a due-journal change.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _committed_list_and_journals(
    async_engine: AsyncEngine,
) -> AsyncIterator[tuple[str, int, int, int]]:
    """A committed list and two future journals under a one-off owner."""
    async with committed_task_list(async_engine) as (owner, list_id):
        async with async_engine.begin() as setup:
            repo = SqlJournalRepository(setup)
            first = await create_journal(
                repo, title="Beach weekend", days_offset=3, user_id=owner
            )
            second = await create_journal(
                repo, title="Hike", days_offset=9, user_id=owner
            )
        try:
            yield owner, list_id, first, second
        finally:
            async with async_engine.begin() as cleanup:
                # The journal writes' events are committed too, and carry no
                # user id the list helper's sweep could find them by.
                await cleanup.execute(
                    text(
                        "DELETE FROM outbox_events "
                        "WHERE event_type LIKE 'Journal%' "
                        "AND aggregate_id = ANY(:journal_ids)"
                    ),
                    {"journal_ids": [first, second]},
                )
                await cleanup.execute(
                    text("DELETE FROM tasks WHERE user_id = :owner"), {"owner": owner}
                )
                await cleanup.execute(
                    text("DELETE FROM journals WHERE user_id = :owner"),
                    {"owner": owner},
                )


def _delete_journal(journal_id: int) -> Callable[[AsyncConnection], Any]:
    async def run(connection: AsyncConnection) -> None:
        await build_journal_service(connection).delete_journal(journal_id, connection)

    return run


def _change_on(
    owner: str,
    task_id: int,
    due_journal_id: int | None,
    outcome: list[BaseException],
) -> Callable[[AsyncConnection], Any]:
    """Change the task's due journal, recording a domain refusal."""

    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.update_task(
                user_id=owner,
                task_id=task_id,
                due_journal_id=due_journal_id,
                transaction=connection,
            )
        except TaskDomainError as error:
            outcome.append(error)

    return run


async def _stored_on(async_engine: AsyncEngine, task_id: int) -> tuple[Any, list[int]]:
    async with async_engine.connect() as check:
        return (
            await _anchors(check, task_id),
            await intermediate_journal_ids(check, task_id),
        )


@pytest.mark.slow
class TestAJournalDeleteRacingTheChange:
    @pytest.mark.asyncio
    async def test_a_set_during_a_delete_of_its_journal_is_told_it_is_gone(
        self, async_engine: AsyncEngine
    ) -> None:
        async with _committed_list_and_journals(async_engine) as (
            owner,
            list_id,
            journal_id,
            _,
        ):
            async with async_engine.begin() as setup:
                task_id = await create_list_task(
                    setup, task_list_id=list_id, user_id=owner
                )
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _delete_journal(journal_id),
                _change_on(owner, task_id, journal_id, refused),
            )

            assert len(refused) == 1
            assert isinstance(refused[0], TaskAnchorJournalNotFoundError)
            assert refused[0].anchor == "due"
            row, linked = await _stored_on(async_engine, task_id)
            assert (row.due_journal_id, linked) == (None, [])
            async with async_engine.connect() as check:
                assert await task_events(check, task_id=task_id) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("replace", [True, False], ids=["replace", "clear"])
    async def test_a_change_during_a_delete_of_the_journal_left_lands(
        self, async_engine: AsyncEngine, replace: bool
    ) -> None:
        """The delete detaches the task first; there is nothing left to retain."""
        async with _committed_list_and_journals(async_engine) as (
            owner,
            list_id,
            old_id,
            new_id,
        ):
            async with async_engine.begin() as setup:
                task_id = await create_list_task(
                    setup, task_list_id=list_id, due_journal_id=old_id, user_id=owner
                )
            outcome: list[BaseException] = []

            await overlap(
                async_engine,
                _delete_journal(old_id),
                _change_on(owner, task_id, new_id if replace else None, outcome),
            )

            assert outcome == []
            row, linked = await _stored_on(async_engine, task_id)
            assert (row.due_journal_id, linked) == (
                new_id if replace else None,
                [],
            )
