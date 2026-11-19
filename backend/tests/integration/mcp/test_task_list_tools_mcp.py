"""Integration tests for the task list MCP tools, over the real MCP endpoint.

The rules are proven against the services in
``tests/integration/tasks/test_task_list_service_integration.py``. These tests
hold the MCP surface to its own promises: the typed results, the refusals an
agent gets back (flagged ``isError``), the provenance a tool records, and that
another user's list is answered exactly as a missing one.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.tasks import MAX_TASK_LIST_NAME_LENGTH, TaskIcon
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    extract_mcp_tool_error,
    extract_typed_tool_result,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    seed_task_list,
    task_list_events,
)

pytestmark = pytest.mark.integration

ARCHIVED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
_COUNT_LISTS = "SELECT COUNT(*) FROM task_lists WHERE user_id = :user_id"


async def _raw_call(client: Any, tool: str, arguments: dict[str, Any]) -> Any:
    response = await client.post(
        "/mcp-server/mcp",
        json=sessionless_mcp_request(
            "tools/call", {"name": tool, "arguments": arguments}
        ),
        headers=sessionless_mcp_headers("tools/call", tool),
    )
    assert response.status_code == 200
    return response


async def _call(client: Any, tool: str, **arguments: Any) -> dict[str, Any]:
    """Call ``tool`` expecting a typed success, and return its result."""
    return extract_typed_tool_result((await _raw_call(client, tool, arguments)).text)


async def _refused(client: Any, tool: str, **arguments: Any) -> dict[str, Any]:
    """Call ``tool`` expecting a domain refusal, and return its payload."""
    return extract_mcp_tool_error((await _raw_call(client, tool, arguments)).text)


def _names(result: dict[str, Any]) -> list[str]:
    return [task_list["name"] for task_list in result["lists"]]


class TestCreateTaskListTool:
    async def test_creates_a_list_and_answers_with_it(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        async with authenticated_lifespan_client() as client:
            created = await _call(
                client, "create_task_list", name="Packing", icon="luggage"
            )

        assert created == {
            "id": created["id"],
            "name": "Packing",
            "icon": "luggage",
            "position": 0,
            "archived": False,
            "archived_at": None,
            "created_at": created["created_at"],
            "updated_at": created["updated_at"],
        }
        assert created["id"] > 0
        assert created["created_at"] is not None

    async def test_the_icon_is_optional(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        async with authenticated_lifespan_client() as client:
            created = await _call(client, "create_task_list", name="Errands")

        assert created["icon"] is None

    async def test_the_created_event_is_attributed_to_the_assistant(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        async with authenticated_lifespan_client() as client:
            created = await _call(client, "create_task_list", name="Packing")

        (event,) = await task_list_events(clean_database, task_list_id=created["id"])
        assert event.payload["user_id"] == USER_ID
        assert (event.payload["source"], event.payload["changed_by"]) == (
            "mcp",
            "mcp",
        )

    @pytest.mark.parametrize("name", ["", "   ", "x" * (MAX_TASK_LIST_NAME_LENGTH + 1)])
    async def test_a_blank_or_too_long_name_is_refused(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        name: str,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            refusal = await _refused(client, "create_task_list", name=name)

        assert refusal["error"] == "Task error"
        assert "name" in refusal["message"]
        assert await count(clean_database, _COUNT_LISTS, {"user_id": USER_ID}) == 0
        assert await task_list_events(clean_database) == []

    async def test_an_icon_outside_the_fixed_set_is_refused(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client, "create_task_list", {"name": "Packing", "icon": "unicorn"}
            )

        # Refused by argument validation, before the tool runs.
        assert '"isError":true' in response.text
        assert "icon" in response.text
        assert await count(clean_database, _COUNT_LISTS, {"user_id": USER_ID}) == 0


class TestGetTaskListTool:
    async def test_reads_one_owned_list(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            clean_database, "Old trip", icon=TaskIcon.LUGGAGE, archived_at=ARCHIVED_AT
        )

        async with authenticated_lifespan_client() as client:
            found = await _call(client, "get_task_list", task_list_id=seeded.id)

        assert found["id"] == seeded.id
        assert (found["name"], found["icon"], found["archived"]) == (
            "Old trip",
            "luggage",
            True,
        )
        assert datetime.fromisoformat(found["archived_at"]) == ARCHIVED_AT

    async def test_another_users_list_is_indistinguishable_from_a_missing_one(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(clean_database, "Theirs", user_id=OTHER_USER_ID)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, "get_task_list", task_list_id=foreign.id)
            missing = await _refused(client, "get_task_list", task_list_id=999_999)

        assert refused["error"] == missing["error"] == "Not found"
        assert refused["message"].replace(str(foreign.id), "X") == missing[
            "message"
        ].replace("999999", "X")
        assert "Theirs" not in str(refused)


class TestListTaskListsTool:
    @pytest.mark.parametrize(
        ("archived", "expected"),
        [
            (None, ["First", "Second"]),
            ("active", ["First", "Second"]),
            ("archived", ["Archived"]),
            ("all", ["First", "Archived", "Second"]),
        ],
    )
    async def test_lists_by_archived_state_in_order(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        archived: str | None,
        expected: list[str],
    ) -> None:
        await seed_task_list(clean_database, "First")
        await seed_task_list(clean_database, "Archived", archived_at=ARCHIVED_AT)
        await seed_task_list(clean_database, "Second")
        arguments = {} if archived is None else {"archived": archived}

        async with authenticated_lifespan_client() as client:
            result = await _call(client, "list_task_lists", **arguments)

        assert _names(result) == expected

    async def test_another_users_lists_are_never_listed(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        await seed_task_list(clean_database, "Mine")
        await seed_task_list(clean_database, "Theirs", user_id=OTHER_USER_ID)
        await seed_task_list(
            clean_database,
            "Theirs archived",
            user_id=OTHER_USER_ID,
            archived_at=ARCHIVED_AT,
        )

        async with authenticated_lifespan_client() as client:
            result = await _call(client, "list_task_lists", archived="all")

        assert _names(result) == ["Mine"]

    async def test_an_unknown_filter_is_refused(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(client, "list_task_lists", {"archived": "yes"})

        assert '"isError":true' in response.text
        assert "archived" in response.text
