"""Integration tests for changing a list task's due date, against a real database.

ITER21-001 Phase 22: ``TaskService.update_task`` sets, changes and clears a
list task's due date as a plain edit. What only a real database can show:

- the stored ``due_date`` column, and the status left as it was;
- one outbox ``TaskUpdated`` carrying the ``(old, new)`` ISO pair, written by
  the same transaction as the row;
- "today" judged on the timezone stored in ``user_settings``, with UTC as the
  fallback when the user has none;
- the read model's ``overdue`` following the new date;
- a refusal leaving the row and the outbox untouched.

The REST and MCP surfaces have their own suites.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from core_shared.models.tasks import (
    TaskDueDateInPastError,
    TaskStatus,
    TaskValidationError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_journal,
    create_list_task,
    seed_task_list_id,
    task_events,
)

pytestmark = pytest.mark.integration

# 06:00 on 6 August in Sydney (+10); the 5th is still running in UTC.
SYDNEY_MORNING = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
UTC_TODAY = date(2026, 8, 5)
SYDNEY_TODAY = date(2026, 8, 6)
LATER = date(2026, 9, 1)
LONG_AGO = date(2026, 7, 1)


async def _stored(conn: AsyncConnection, task_id: int) -> Any:
    return (
        await conn.execute(
            text("SELECT due_date, status FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
    ).one()


async def _redate(
    service: TaskService,
    conn: AsyncConnection,
    task_id: int,
    due_date: date | None,
    *,
    user_id: str = USER_ID,
) -> None:
    await service.update_task(
        user_id=user_id,
        task_id=task_id,
        due_date=due_date,
        transaction=conn,
        now=SYDNEY_MORNING,
    )


class TestSetChangeAndClear:
    @pytest.mark.parametrize(
        ("before", "after", "pair"),
        [
            (None, LATER, [None, "2026-09-01"]),
            (LATER, date(2026, 9, 15), ["2026-09-01", "2026-09-15"]),
            (LATER, None, ["2026-09-01", None]),
        ],
        ids=["set", "changed", "cleared"],
    )
    async def test_the_row_and_one_event_carry_the_change(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        before: date | None,
        after: date | None,
        pair: list[str | None],
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=before
        )

        await _redate(service, async_connection, task_id, after)

        row = await _stored(async_connection, task_id)
        assert (row.due_date, row.status) == (after, TaskStatus.NOT_DONE.value)
        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"due_date": pair}

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_closed_task_is_redated_and_stays_closed(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        status: TaskStatus,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, status=status
        )

        await _redate(service, async_connection, task_id, LATER)

        row = await _stored(async_connection, task_id)
        assert (row.due_date, row.status) == (LATER, status.value)

    async def test_an_overdue_task_redated_to_today_is_no_longer_overdue(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=LONG_AGO
        )
        before = await read_service.read_model(USER_ID, task_id, now=SYDNEY_MORNING)
        assert before.overdue is True

        await _redate(service, async_connection, task_id, UTC_TODAY)

        after = await read_service.read_model(USER_ID, task_id, now=SYDNEY_MORNING)
        assert after.overdue is False
        assert after.task.due_date == UTC_TODAY

    async def test_resending_an_overdue_tasks_own_date_writes_nothing(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=LONG_AGO
        )

        await _redate(service, async_connection, task_id, LONG_AGO)

        assert (await _stored(async_connection, task_id)).due_date == LONG_AGO
        assert await task_events(async_connection, task_id=task_id) == []


class TestTodayIsTheUsers:
    async def test_utc_today_is_already_yesterday_in_sydney(
        self,
        service: TaskService,
        user_settings_repository: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        with pytest.raises(TaskDueDateInPastError) as raised:
            await _redate(service, async_connection, task_id, UTC_TODAY)

        assert raised.value.today == SYDNEY_TODAY
        assert (await _stored(async_connection, task_id)).due_date is None
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_sydneys_today_is_accepted(
        self,
        service: TaskService,
        user_settings_repository: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        await _redate(service, async_connection, task_id, SYDNEY_TODAY)

        assert (await _stored(async_connection, task_id)).due_date == SYDNEY_TODAY

    async def test_without_a_stored_timezone_utc_today_is_accepted(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        user_id = f"no-settings-{uuid.uuid4()}"
        list_id = await seed_task_list_id(async_connection, user_id=user_id)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, user_id=user_id
        )

        await _redate(service, async_connection, task_id, UTC_TODAY, user_id=user_id)

        assert (await _stored(async_connection, task_id)).due_date == UTC_TODAY


class TestTheInvariantsHold:
    async def test_a_task_due_in_a_journal_keeps_its_journal(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Replacing a due journal with a date is ITER21-001 Phase 23's."""
        journal_id = await create_journal(journal_repository, days_offset=7)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=journal_id
        )

        with pytest.raises(TaskValidationError) as raised:
            await _redate(service, async_connection, task_id, LATER)

        assert raised.value.field == "due_date"
        assert (await _stored(async_connection, task_id)).due_date is None
        assert await task_events(async_connection, task_id=task_id) == []
