"""Integration tests for ``POST /api/tasks/{task_id}/move``.

The service's rules — bottom of the list, lock order, the refusal order — are
proved in ``tests/integration/tasks/test_task_service_move_to_list_integration.py``.
This file proves what reaches a client: the status codes and error codes, that
the response is the moved task with its trail, that the read afterwards no
longer reports a lapse, that the event carries UI provenance, and that another
user's task or list is the same 404 as an absent one with nothing written.
"""

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


def _move_body(task_list_id: Any) -> dict[str, Any]:
    return {
        "data": {"type": "task-moves", "attributes": {"task_list_id": task_list_id}}
    }


async def _list_id(conn: AsyncConnection, name: str, **kwargs: Any) -> int:
    task_list = await seed_task_list(conn, name, **kwargs)
    assert task_list.id is not None
    return task_list.id


def _error_code(response: Any) -> str:
    (error,) = response.json()["errors"]
    return str(error["code"])


class TestMovingATask:
    async def test_a_journal_only_task_joins_a_list_and_stops_lapsing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        creating_id = await create_journal(
            journal_repository, title="Planning", days_offset=-5
        )
        due_id = await create_journal(journal_repository, title="Due", days_offset=-3)
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        list_id = await _list_id(async_connection, "Packing")
        before = await authenticated_client.get(f"/api/tasks/{task_id}")
        assert before.json()["data"]["attributes"]["lapsed"] is True

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(list_id)
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["type"] == "tasks"
        assert data["id"] == str(task_id)
        assert data["attributes"]["task_list_id"] == list_id
        assert data["attributes"]["due_journal_id"] == due_id
        assert data["attributes"]["intermediate_journal_ids"] == []
        after = await authenticated_client.get(f"/api/tasks/{task_id}")
        assert after.json()["data"]["attributes"]["lapsed"] is False
        assert after.json()["data"]["attributes"]["overdue"] is True

    async def test_a_list_task_moves_to_the_bottom_of_another_list(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        source_id = await _list_id(async_connection, "Groceries")
        target_id = await _list_id(async_connection, "Hardware")
        task_id = await create_list_task(async_connection, task_list_id=source_id)
        await create_list_task(async_connection, task_list_id=target_id, position=3)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(target_id)
        )

        assert response.status_code == 200
        assert await stored_membership(async_connection, task_id) == (target_id, 4)
        [event] = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskListMembershipChanged"
        assert event.payload["changed_fields"] == {
            "task_list_id": [source_id, target_id]
        }
        assert event.payload["source"] == "ui"
        assert event.payload["changed_by"] == "ui"

    async def test_moving_to_its_own_list_is_a_no_op(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(async_connection, task_list_id=list_id)
        await create_list_task(async_connection, task_list_id=list_id, position=1)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(list_id)
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["task_list_id"] == list_id
        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []


class TestMalformedRequests:
    @pytest.mark.parametrize(
        "body",
        [
            {"data": {"type": "tasks", "attributes": {"task_list_id": 1}}},
            {"data": {"type": "task-moves", "attributes": {"task_list_id": 1, "x": 1}}},
            _move_body("1"),
            _move_body(True),
            _move_body(None),
            _move_body(0),
            _move_body(INT32_MAX + 1),
            {"data": {"type": "task-moves", "attributes": {}}},
        ],
        ids=[
            "wrong-type",
            "extra-attribute",
            "string-id",
            "boolean-id",
            "null",
            "zero",
            "out-of-range",
            "missing",
        ],
    )
    async def test_the_body_is_refused_and_nothing_moves(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        body: dict[str, Any],
    ) -> None:
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=body
        )

        assert response.status_code == 400
        assert await stored_membership(async_connection, task_id) == (list_id, 0)


class TestRefusals:
    async def test_an_unknown_task_is_not_found(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _list_id(async_connection, "Groceries")

        response = await authenticated_client.post(
            "/api/tasks/999999/move", json=_move_body(list_id)
        )

        assert response.status_code == 404
        assert _error_code(response) == "TASK_NOT_FOUND"

    async def test_an_unknown_list_is_not_found(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(999_999)
        )

        assert response.status_code == 404
        assert _error_code(response) == "TASK_LIST_NOT_FOUND"
        assert await stored_membership(async_connection, task_id) == (list_id, 0)

    async def test_a_task_on_an_archived_list_cannot_leave_it(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        archived_id = await _list_id(async_connection, "Old", archived_at=ARCHIVED_AT)
        target_id = await _list_id(async_connection, "New")
        task_id = await create_list_task(async_connection, task_list_id=archived_id)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(target_id)
        )

        assert response.status_code == 409
        assert _error_code(response) == "TASK_LIST_ARCHIVED"
        assert await stored_membership(async_connection, task_id) == (archived_id, 0)

    async def test_an_archived_list_takes_no_task(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        source_id = await _list_id(async_connection, "Groceries")
        archived_id = await _list_id(async_connection, "Old", archived_at=ARCHIVED_AT)
        task_id = await create_list_task(async_connection, task_list_id=source_id)

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(archived_id)
        )

        assert response.status_code == 409
        assert _error_code(response) == "TASK_LIST_ARCHIVED"
        assert await task_events(async_connection, task_id=task_id) == []


class TestASecondUser:
    async def test_their_task_is_the_same_404_as_an_absent_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        theirs_id = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        mine_id = await _list_id(async_connection, "Mine")
        task_id = await create_list_task(
            async_connection, task_list_id=theirs_id, user_id=OTHER_USER_ID
        )

        foreign = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(mine_id)
        )
        absent = await authenticated_client.post(
            "/api/tasks/999999/move", json=_move_body(mine_id)
        )

        assert foreign.status_code == absent.status_code == 404
        assert _error_code(foreign) == _error_code(absent)
        assert await stored_membership(async_connection, task_id) == (theirs_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_their_list_is_the_same_404_as_an_absent_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        mine_id = await _list_id(async_connection, "Mine")
        theirs_id = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        task_id = await create_list_task(async_connection, task_list_id=mine_id)

        foreign = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(theirs_id)
        )
        absent = await authenticated_client.post(
            f"/api/tasks/{task_id}/move", json=_move_body(999_999)
        )

        assert foreign.status_code == absent.status_code == 404
        assert _error_code(foreign) == _error_code(absent) == "TASK_LIST_NOT_FOUND"
        assert await stored_membership(async_connection, task_id) == (mine_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []
