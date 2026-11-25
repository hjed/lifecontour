"""Integration tests: ``PATCH /api/tasks/{id}`` reopens a list task directly.

The specification: *"For list tasks, reopening is direct: a done or cancelled
list task can be set back to not done, without retargeting. Journal-only tasks
keep the existing rules."* Cancelled → done is open on a list too (user
decision in the Phase 24 plan review). No new route: the existing status write
answers it, which is the phase's acceptance criterion.

What the stored row does on a reopen — ``closed_at``, position, the outbox — is
proved in ``tests/integration/tasks/test_task_service_list_reopen_integration.py``;
this file is about what reaches the client.
"""

import pytest
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_journal,
    create_list_task,
    create_task,
    seed_task_list,
    stored_status,
)

pytestmark = pytest.mark.integration


async def _list_id(conn: AsyncConnection, *, user_id: str = USER_ID) -> int:
    task_list = await seed_task_list(conn, user_id=user_id)
    assert task_list.id is not None
    return task_list.id


def _status_body(task_id: int, status: str) -> dict[str, object]:
    return {
        "data": {"type": "tasks", "id": str(task_id), "attributes": {"status": status}}
    }


class TestAListTaskIsReopenedByItsStatus:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TaskStatus.CANCELLED, "not_done"),
            (TaskStatus.DONE, "not_done"),
            (TaskStatus.CANCELLED, "done"),
        ],
    )
    async def test_the_status_write_answers_200(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        current: TaskStatus,
        target: str,
    ) -> None:
        """No retarget, no journal named: the status alone does it."""
        task_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection),
            status=current,
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_status_body(task_id, target)
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert attributes["status"] == target
        assert await stored_status(async_connection, task_id) == target

    async def test_a_journal_only_cancelled_task_is_still_refused(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The journal-only rule is unchanged: 409, naming retargeting."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{task_id}", json=_status_body(task_id, "not_done")
        )

        assert response.status_code == 409
        (error,) = response.json()["errors"]
        assert error["code"] == "TASK_STATUS_TRANSITION_REFUSED"
        assert "retarget" in str(error["detail"]).lower()
        assert await stored_status(async_connection, task_id) == "cancelled"


class TestAClosedListTaskIsRetargetedWithoutReopening:
    """A closed list task's due journal moves directly, and it stays closed.

    Reopening it first is no longer needed: changing a list task's date never
    changes its status, so the retarget simply keeps the one it has.
    """

    @pytest.mark.parametrize("closed", [TaskStatus.CANCELLED, TaskStatus.DONE])
    async def test_the_retarget_keeps_its_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        closed: TaskStatus,
    ) -> None:
        due_id = await create_journal(journal_repository, days_offset=5)
        later_id = await create_journal(journal_repository, days_offset=9)
        task_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection),
            due_journal_id=due_id,
            status=closed,
        )

        retargeted = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json={
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": later_id},
                }
            },
        )

        assert retargeted.status_code == 200
        attributes = retargeted.json()["data"]["attributes"]
        assert (attributes["status"], attributes["due_journal_id"]) == (
            closed.value,
            later_id,
        )
        assert await stored_status(async_connection, task_id) == closed.value


class TestAnotherUsersListTask:
    async def test_reads_as_a_missing_one_and_is_not_reopened(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """404 with the same error code as an id that does not exist.

        The detail names the requested id, so the two bodies differ only there.
        """
        foreign_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection, user_id=OTHER_USER_ID),
            status=TaskStatus.CANCELLED,
            user_id=OTHER_USER_ID,
        )
        missing_id = foreign_id + 1000

        foreign = await authenticated_client.patch(
            f"/api/tasks/{foreign_id}", json=_status_body(foreign_id, "not_done")
        )
        missing = await authenticated_client.patch(
            f"/api/tasks/{missing_id}", json=_status_body(missing_id, "not_done")
        )

        assert foreign.status_code == missing.status_code == 404
        (foreign_error,) = foreign.json()["errors"]
        (missing_error,) = missing.json()["errors"]
        assert foreign_error["code"] == missing_error["code"]
        assert await stored_status(async_connection, foreign_id) == "cancelled"
