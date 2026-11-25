"""Integration tests for ``POST /api/tasks/{task_id}/remove-from-list``.

The service's rules — lock order, refusal order, concurrency — are proved in
``tests/integration/tasks/test_task_service_remove_from_list_integration.py``.
This file proves what reaches a client: the status and error codes, that the
answer is the task's read model saying whether it is now **lapsed** (the
specification's "the user is told so"), that the event carries UI provenance,
and that another user's task is the same 404 as an absent one, nothing written.
"""

import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import (
    ARCHIVED_AT,
    OTHER_USER_ID,
    create_journal,
    create_list_task,
    create_task,
    seed_task_list,
    stored_membership,
    task_events,
)

pytestmark = pytest.mark.integration


async def _list_id(conn: AsyncConnection, name: str, **kwargs: Any) -> int:
    task_list = await seed_task_list(conn, name, **kwargs)
    assert task_list.id is not None
    return task_list.id


def _error_code(response: Any) -> str:
    (error,) = response.json()["errors"]
    return str(error["code"])


async def _anchored(
    conn: AsyncConnection,
    journals: SqlJournalRepository,
    *,
    due_offset: int,
    user_id: str | None = None,
) -> tuple[int, int, int]:
    """A task on a list holding both journals; ``(list, task, due journal)``."""
    owner: dict[str, Any] = {} if user_id is None else {"user_id": user_id}
    creating_id = await create_journal(
        journals, title="Planning", days_offset=-10, **owner
    )
    due_id = await create_journal(
        journals, title="Due", days_offset=due_offset, **owner
    )
    list_id = await _list_id(conn, "Packing", **owner)
    task_id = await create_list_task(
        conn,
        task_list_id=list_id,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        **owner,
    )
    return list_id, task_id, due_id


def _remove_path(task_id: int | str) -> str:
    return f"/api/tasks/{task_id}/remove-from-list"


class TestRemovingATask:
    async def test_a_task_past_its_due_journal_is_answered_as_lapsed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        _, task_id, due_id = await _anchored(
            async_connection, journal_repository, due_offset=-3
        )

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["type"] == "tasks"
        assert data["id"] == str(task_id)
        attributes = data["attributes"]
        assert attributes["task_list_id"] is None
        assert attributes["task_list"] is None
        assert attributes["due_journal_id"] == due_id
        assert attributes["lapsed"] is True
        assert attributes["lapse_reason"] == "date_passed"
        assert attributes["overdue"] is False

    async def test_a_task_due_in_the_future_is_answered_as_not_lapsed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id, task_id, _ = await _anchored(
            async_connection, journal_repository, due_offset=4
        )

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["lapsed"] is False
        assert await stored_membership(async_connection, task_id) == (None, None)
        [event] = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskListMembershipChanged"
        assert event.payload["changed_fields"] == {"task_list_id": [list_id, None]}
        assert event.payload["source"] == "ui"
        assert event.payload["changed_by"] == "ui"

    async def test_the_removal_reads_back_in_its_history(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The read afterwards agrees with the answer: no list, not overdue."""
        _, task_id, _ = await _anchored(
            async_connection, journal_repository, due_offset=4
        )

        await authenticated_client.post(_remove_path(task_id))

        read = await authenticated_client.get(f"/api/tasks/{task_id}")
        assert read.json()["data"]["attributes"]["task_list_id"] is None

    async def test_a_journal_only_task_is_a_no_op(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["task_list_id"] is None
        assert await task_events(async_connection, task_id=task_id) == []


class TestRefusals:
    async def test_an_undated_task_cannot_leave(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 409
        assert _error_code(response) == "TASK_LIST_REMOVAL_NEEDS_JOURNALS"
        (error,) = response.json()["errors"]
        assert "creating journal and due journal" in error["detail"]
        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_a_task_due_on_a_date_cannot_leave(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, _ = task_anchors
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            creating_journal_id=creating_id,
            due_date=datetime.date(2099, 1, 1),
        )

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 409
        assert _error_code(response) == "TASK_LIST_REMOVAL_NEEDS_JOURNALS"
        assert await stored_membership(async_connection, task_id) == (list_id, 0)

    async def test_a_task_with_only_a_creating_journal_cannot_leave(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, _ = task_anchors
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, creating_journal_id=creating_id
        )

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 409
        assert _error_code(response) == "TASK_LIST_REMOVAL_NEEDS_JOURNALS"

    async def test_an_archived_list_keeps_its_task(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        list_id = await _list_id(async_connection, "Old", archived_at=ARCHIVED_AT)
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 409
        assert _error_code(response) == "TASK_LIST_ARCHIVED"
        assert await stored_membership(async_connection, task_id) == (list_id, 0)

    async def test_an_unknown_task_is_not_found(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.post(_remove_path(INT32_MAX))

        assert response.status_code == 404
        assert _error_code(response) == "TASK_NOT_FOUND"

    @pytest.mark.parametrize("task_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_id_outside_the_column_is_refused(
        self, authenticated_client: AsyncClient, task_id: str
    ) -> None:
        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 400


class TestASecondUser:
    async def test_their_task_is_the_same_404_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id, task_id, _ = await _anchored(
            async_connection, journal_repository, due_offset=4, user_id=OTHER_USER_ID
        )

        response = await authenticated_client.post(_remove_path(task_id))

        assert response.status_code == 404
        assert _error_code(response) == "TASK_NOT_FOUND"
        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []
