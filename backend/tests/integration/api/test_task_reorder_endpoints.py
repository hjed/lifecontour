"""Integration tests for ``POST /api/tasks/{task_id}/reorder``.

The list page's single move: one open task to the top of its list, or directly
after another open task on it. What reaches the client — the list's open tasks
in their new order — each refusal's status and code, and that another user's
task or anchor reads exactly as an absent one with nothing moved. Reordering is
not recorded: no event, no history. The rules, the lock order and the races are
proved against the service in ``tests/integration/tasks/``.
"""

from typing import Any

import pytest
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    count,
    create_list_task,
    create_task,
    seed_task_list_id,
    stored_positions,
)

pytestmark = pytest.mark.integration

_COUNT_OUTBOX = "SELECT COUNT(*) FROM outbox_events"
_COUNT_HISTORY = "SELECT COUNT(*) FROM field_history"


def _body(after_task_id: object) -> dict[str, Any]:
    return {
        "data": {
            "type": "task-reorders",
            "attributes": {"after_task_id": after_task_id},
        }
    }


async def _reorder(
    client: AsyncClient, task_id: int | str, body: dict[str, Any]
) -> Response:
    return await client.post(f"/api/tasks/{task_id}/reorder", json=body)


def _error(response: Response) -> dict[str, Any]:
    (error,) = response.json()["errors"]
    first: dict[str, Any] = error
    return first


async def _seed(conn: AsyncConnection) -> tuple[int, list[int]]:
    """A list with open tasks at 0, 1 and 2; ``(list, ids)``."""
    list_id = await seed_task_list_id(conn)
    ids = [
        await create_list_task(conn, task_list_id=list_id, position=position)
        for position in (0, 1, 2)
    ]
    return list_id, ids


class TestReordering:
    async def test_answers_the_open_tasks_in_their_new_order(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id, (first, second, third) = await _seed(async_connection)

        response = await _reorder(authenticated_client, third, _body(first))

        assert response.status_code == 200
        data = response.json()["data"]
        assert [int(each["id"]) for each in data] == [first, third, second]
        assert {each["type"] for each in data} == {"tasks"}
        assert {each["attributes"]["task_list_id"] for each in data} == {list_id}
        assert await stored_positions(async_connection, [first, third, second]) == [
            0,
            1,
            2,
        ]

    async def test_null_moves_the_task_to_the_top(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        _, (first, second, third) = await _seed(async_connection)

        response = await _reorder(authenticated_client, second, _body(None))

        assert response.status_code == 200
        assert [int(each["id"]) for each in response.json()["data"]] == [
            second,
            first,
            third,
        ]

    async def test_reordering_records_nothing(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection)
        outbox = await count(async_connection, _COUNT_OUTBOX, {})
        history = await count(async_connection, _COUNT_HISTORY, {})

        response = await _reorder(authenticated_client, ids[2], _body(None))

        assert response.status_code == 200
        assert await count(async_connection, _COUNT_OUTBOX, {}) == outbox
        assert await count(async_connection, _COUNT_HISTORY, {}) == history


class TestRefusals:
    async def test_a_task_cannot_follow_itself(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection)

        response = await _reorder(authenticated_client, ids[1], _body(ids[1]))

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"] == {"field": "after_task_id"}
        assert await stored_positions(async_connection, ids) == [0, 1, 2]

    async def test_a_journal_only_task_has_no_order(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await _reorder(authenticated_client, task_id, _body(None))

        assert response.status_code == 400
        assert _error(response)["meta"] == {"field": "task_id"}

    async def test_a_closed_task_is_refused(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id, ids = await _seed(async_connection)
        closed = await create_list_task(
            async_connection, task_list_id=list_id, position=3, status=TaskStatus.DONE
        )

        response = await _reorder(authenticated_client, closed, _body(None))

        assert response.status_code == 400
        assert _error(response)["meta"] == {"field": "task_id"}
        assert await stored_positions(async_connection, [*ids, closed]) == [0, 1, 2, 3]

    async def test_a_closed_anchor_is_refused(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id, ids = await _seed(async_connection)
        closed = await create_list_task(
            async_connection, task_list_id=list_id, position=3, status=TaskStatus.DONE
        )

        response = await _reorder(authenticated_client, ids[2], _body(closed))

        assert response.status_code == 400
        assert _error(response)["meta"] == {"field": "after_task_id"}
        assert await stored_positions(async_connection, ids) == [0, 1, 2]

    async def test_an_anchor_on_another_list_is_refused(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection)
        elsewhere = await seed_task_list_id(async_connection)
        anchor = await create_list_task(async_connection, task_list_id=elsewhere)

        response = await _reorder(authenticated_client, ids[2], _body(anchor))

        assert response.status_code == 400
        assert _error(response)["meta"] == {"field": "after_task_id"}
        assert await stored_positions(async_connection, ids) == [0, 1, 2]

    async def test_another_users_task_reads_as_a_missing_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        their_list = await seed_task_list_id(async_connection, user_id=OTHER_USER_ID)
        theirs = [
            await create_list_task(
                async_connection,
                task_list_id=their_list,
                position=position,
                user_id=OTHER_USER_ID,
            )
            for position in (0, 1)
        ]

        foreign = await _reorder(authenticated_client, theirs[1], _body(None))
        missing = await _reorder(authenticated_client, 2_000_000_000, _body(None))

        assert foreign.status_code == missing.status_code == 404
        assert _error(foreign)["code"] == _error(missing)["code"] == "TASK_NOT_FOUND"
        assert await stored_positions(async_connection, theirs) == [0, 1]

    async def test_another_users_anchor_reads_as_a_missing_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection)
        their_list = await seed_task_list_id(async_connection, user_id=OTHER_USER_ID)
        theirs = await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )

        foreign = await _reorder(authenticated_client, ids[2], _body(theirs))
        missing = await _reorder(authenticated_client, ids[2], _body(2_000_000_000))

        assert foreign.status_code == missing.status_code == 404
        assert _error(foreign)["code"] == _error(missing)["code"] == "TASK_NOT_FOUND"
        assert await stored_positions(async_connection, ids) == [0, 1, 2]

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                {"data": {"type": "task-reorders", "attributes": {}}}, id="no-anchor"
            ),
            pytest.param(_body(True), id="boolean"),
            pytest.param(_body("1"), id="string"),
            pytest.param(_body(0), id="zero"),
            pytest.param(_body(INT32_MAX + 1), id="too-large"),
            pytest.param(
                {"data": {"type": "tasks", "attributes": {"after_task_id": None}}},
                id="another-type",
            ),
        ],
    )
    async def test_a_malformed_body_is_refused_and_nothing_moves(
        self,
        body: dict[str, Any],
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        _, ids = await _seed(async_connection)

        response = await _reorder(authenticated_client, ids[2], body)

        assert response.status_code == 400
        assert _error(response)["code"] == "VALIDATION_ERROR"
        assert await stored_positions(async_connection, ids) == [0, 1, 2]

    @pytest.mark.parametrize("task_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, task_id: str
    ) -> None:
        response = await _reorder(authenticated_client, task_id, _body(None))

        assert response.status_code == 400
