"""Integration tests for a list task's due date on ``PATCH /api/tasks/{task_id}``.

ITER21-001 Phase 22, through the REST surface: what reaches the client when a
due date is set, changed or cleared, each refusal's status and JSON:API code,
and that another user's task reads as an absent one with nothing written. The
rules themselves — "today" in the user's timezone included — are proved against
the service in ``tests/integration/tasks/test_task_service_due_date_integration.py``;
this file is about the surface.
"""

from datetime import date
from typing import Any

import pytest
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    create_journal,
    create_list_task,
    create_task,
    seed_task_list_id,
    stored_marks,
    task_events,
)

pytestmark = pytest.mark.integration

# Far enough either side of the real clock that no timezone moves them.
FUTURE = date(2099, 12, 31)
LATER_FUTURE = date(2100, 1, 15)
PAST = date(2000, 1, 1)


def _body(task_id: int, **attributes: object) -> dict[str, object]:
    return {"data": {"type": "tasks", "id": str(task_id), "attributes": attributes}}


async def _patch(client: AsyncClient, task_id: int, **attributes: object) -> Response:
    return await client.patch(
        f"/api/tasks/{task_id}", json=_body(task_id, **attributes)
    )


def _error(response: Response) -> dict[str, Any]:
    (error,) = response.json()["errors"]
    first: dict[str, Any] = error
    return first


async def _stored(conn: AsyncConnection, task_id: int) -> Any:
    return (
        await conn.execute(
            text("SELECT due_date, status, due_journal_id FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
    ).one()


class TestSetChangeAndClear:
    @pytest.mark.parametrize(
        ("before", "sent", "after", "pair"),
        [
            (None, "2099-12-31", FUTURE, [None, "2099-12-31"]),
            (FUTURE, "2100-01-15", LATER_FUTURE, ["2099-12-31", "2100-01-15"]),
            (FUTURE, None, None, ["2099-12-31", None]),
        ],
        ids=["set", "changed", "cleared"],
    )
    async def test_answers_200_and_announces_one_change(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        before: date | None,
        sent: str | None,
        after: date | None,
        pair: list[str | None],
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=before
        )

        response = await _patch(authenticated_client, task_id, due_date=sent)

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert attributes["due_date"] == (None if after is None else after.isoformat())
        assert attributes["status"] == "not_done"
        assert attributes["task_list_id"] == list_id
        row = await _stored(async_connection, task_id)
        assert (row.due_date, row.status) == (after, "not_done")
        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"due_date": pair}
        assert (event.payload["source"], event.payload["changed_by"]) == ("ui", "ui")

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_closed_task_is_redated_with_no_acknowledgement(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        status: TaskStatus,
    ) -> None:
        """A plain edit: the status is kept, so nothing reopens."""
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, status=status
        )

        response = await _patch(authenticated_client, task_id, due_date="2099-12-31")

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["status"] == status.value
        assert (await _stored(async_connection, task_id)).status == status.value

    async def test_an_overdue_task_redated_reads_back_not_overdue(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=PAST
        )
        before = await authenticated_client.get(f"/api/tasks/{task_id}")
        assert before.json()["data"]["attributes"]["overdue"] is True

        await _patch(authenticated_client, task_id, due_date="2099-12-31")

        after = await authenticated_client.get(f"/api/tasks/{task_id}")
        assert after.json()["data"]["attributes"]["overdue"] is False
        assert after.json()["data"]["attributes"]["due_date"] == "2099-12-31"

    async def test_resending_an_overdue_tasks_own_date_is_a_quiet_200(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """The today-or-later rule judges a date being *set*; this one is not."""
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=PAST
        )

        response = await _patch(authenticated_client, task_id, due_date="2000-01-01")

        assert response.status_code == 200
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_a_date_and_a_flag_in_one_body_are_one_event(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await _patch(
            authenticated_client, task_id, due_date="2099-12-31", flagged=True
        )

        assert response.status_code == 200
        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.payload["changed_fields"] == {
            "flagged": [False, True],
            "due_date": [None, "2099-12-31"],
        }

    async def test_a_task_due_in_a_journal_has_it_replaced_by_the_date(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Invariant 4, by replacement: the journal left becomes intermediate."""
        journal_id = await create_journal(journal_repository, days_offset=7)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=journal_id
        )

        response = await _patch(authenticated_client, task_id, due_date="2099-12-31")

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert (attributes["due_date"], attributes["due_journal_id"]) == (
            "2099-12-31",
            None,
        )
        assert attributes["intermediate_journal_ids"] == [journal_id]
        row = await _stored(async_connection, task_id)
        assert (row.due_date, row.due_journal_id) == (FUTURE, None)


class TestRefusals:
    async def test_a_past_date_is_refused_naming_both_days(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await _patch(authenticated_client, task_id, due_date="2000-01-01")

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_DUE_DATE_IN_PAST"
        assert "2000-01-01" in error["detail"]
        assert (await _stored(async_connection, task_id)).due_date is None
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_a_journal_only_task_takes_no_due_date(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Invariant 5: a due date only on a task that is on a list."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await _patch(authenticated_client, task_id, due_date="2099-12-31")

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"]["field"] == "due_date"
        assert (await _stored(async_connection, task_id)).due_date is None
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.parametrize(
        "value",
        [20991231, "31/12/2099", "2099-12-31T00:00:00Z", ""],
        ids=["numeric", "local-format", "datetime", "empty"],
    )
    async def test_anything_but_an_iso_day_is_a_validation_error(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        value: object,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await _patch(authenticated_client, task_id, due_date=value)

        assert response.status_code == 400
        assert _error(response)["code"] == "VALIDATION_ERROR"
        assert (await _stored(async_connection, task_id)).due_date is None
        assert await task_events(async_connection, task_id=task_id) == []


class TestAnotherUsersTask:
    async def test_is_answered_as_an_absent_one_and_left_alone(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """Byte-identical once the ids are stripped, so no id can be probed."""
        foreign_list = await seed_task_list_id(async_connection, user_id=OTHER_USER_ID)
        foreign_task = await create_list_task(
            async_connection,
            task_list_id=foreign_list,
            due_date=FUTURE,
            user_id=OTHER_USER_ID,
        )

        foreign = await _patch(authenticated_client, foreign_task, due_date=None)
        absent = await _patch(authenticated_client, 999_999, due_date=None)

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign), _error(absent)
        assert foreign_error["code"] == absent_error["code"] == "TASK_NOT_FOUND"
        assert foreign_error["detail"].replace(str(foreign_task), "X") == absent_error[
            "detail"
        ].replace("999999", "X")
        assert (await _stored(async_connection, foreign_task)).due_date == FUTURE
        assert await stored_marks(async_connection, foreign_task) == (False, None)
        assert await task_events(async_connection, task_id=foreign_task) == []
