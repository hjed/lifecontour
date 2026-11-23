"""Integration tests: ``set_task_status`` reopens a list task directly.

The MCP twin of ``tests/integration/api/test_task_list_reopen_endpoints.py``. A
done or cancelled list task is set back to not done with the existing tool, no
retarget involved; cancelled → done is open on a list too (user decision in the
Phase 24 plan review). A journal-only cancelled task is still refused with the
message that sends a model to ``retarget_task``, and another user's task reads
exactly like a missing one.
"""

from typing import Any

import pytest
from core_shared.models.tasks import TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.mcp.domains.tasks.schemas import TaskMCP
from tests.integration.mcp.http_helpers import (
    extract_mcp_tool_error,
    extract_typed_tool_result,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
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


async def _call(client: Any, **arguments: Any) -> Any:
    response = await client.post(
        "/mcp-server/mcp",
        json=sessionless_mcp_request(
            "tools/call", {"name": "set_task_status", "arguments": arguments}
        ),
        headers=sessionless_mcp_headers("tools/call", "set_task_status"),
    )
    assert response.status_code == 200
    return response


class TestSetTaskStatusReopensAListTask:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TaskStatus.CANCELLED, "not_done"),
            (TaskStatus.DONE, "not_done"),
            (TaskStatus.CANCELLED, "done"),
        ],
    )
    async def test_the_status_alone_does_it(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        current: TaskStatus,
        target: str,
    ) -> None:
        """Typed, matching the published answer, and stored."""
        task_id = await create_list_task(
            clean_database,
            task_list_id=await _list_id(clean_database),
            status=current,
        )

        async with authenticated_lifespan_client() as client:
            response = await _call(client, task_id=task_id, status=target)

        payload = extract_typed_tool_result(response.text)
        TaskMCP.model_validate(payload)
        assert payload["status"] == target
        assert await stored_status(clean_database, task_id) == target

    async def test_a_journal_only_cancelled_task_is_still_sent_to_retarget(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The journal-only rule is unchanged, refusal message included."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        async with authenticated_lifespan_client() as client:
            response = await _call(client, task_id=task_id, status="not_done")

        error = extract_mcp_tool_error(response.text)
        assert error["error"] == "Task error"
        assert "retarget" in error["message"].lower()
        assert await stored_status(clean_database, task_id) == "cancelled"


class TestAnotherUsersListTask:
    async def test_reads_as_a_missing_one_and_is_not_reopened(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        """The same refusal as an id that does not exist."""
        foreign_id = await create_list_task(
            clean_database,
            task_list_id=await _list_id(clean_database, user_id=OTHER_USER_ID),
            status=TaskStatus.CANCELLED,
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            foreign = extract_mcp_tool_error(
                (await _call(client, task_id=foreign_id, status="not_done")).text
            )
            missing = extract_mcp_tool_error(
                (await _call(client, task_id=999_999, status="not_done")).text
            )

        assert foreign["error"] == missing["error"] == "Not found"
        assert await stored_status(clean_database, foreign_id) == "cancelled"
