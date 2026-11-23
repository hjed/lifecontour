"""Integration tests: every task write tool refuses a task on an archived list.

The MCP half of Phase 18, over the real MCP endpoint, and creating a task on an
archived list. Each of the eight task write tools answers an archived list's task with a "Task error" whose message
names unarchiving as the way out — the same text the REST surface carries — and
leaves the task as it was. ``get_task`` still answers, because an archived
list's tasks stay readable.

The rule and its lock are proved against the service in
``tests/integration/tasks/test_task_service_archived_list_integration.py``.
"""

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.mcp.http_helpers import (
    extract_mcp_tool_error,
    extract_typed_tool_result,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)
from tests.integration.tasks.task_seeding import (
    ArchivedListTask,
    count,
    create_journal,
    seed_archived_list_task,
    task_events,
    task_state,
)

pytestmark = pytest.mark.integration

COUNT_LIST_TASKS = "SELECT COUNT(*) FROM tasks WHERE task_list_id = :task_list_id"


@pytest_asyncio.fixture
async def seeded(
    clean_database: AsyncConnection,
    journal_repository: SqlJournalRepository,
    task_anchors: tuple[int, int],
) -> ArchivedListTask:
    return await seed_archived_list_task(
        clean_database, journal_repository, task_anchors
    )


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


def _calls(s: ArchivedListTask) -> list[tuple[str, dict[str, Any]]]:
    """Each write tool, with arguments that would succeed on an active list."""
    return [
        ("set_task_status", {"task_id": s.task_id, "status": "done"}),
        ("update_task", {"task_id": s.task_id, "text": "pack the spare torch"}),
        ("update_task:flag", {"task_id": s.task_id, "flagged": True}),
        ("update_task:icon", {"task_id": s.task_id, "icon": "tent"}),
        ("update_task:clear-icon", {"task_id": s.task_id, "clear_icon": True}),
        # The seeded task is due in a journal, which no date may join: the
        # archived answer comes before that invariant, as before every rule.
        ("update_task:due-date", {"task_id": s.task_id, "due_date": "2099-12-31"}),
        (
            "update_task:clear-due-date",
            {"task_id": s.task_id, "clear_due_date": True},
        ),
        ("delete_task", {"task_id": s.task_id}),
        ("retarget_task", {"task_id": s.task_id, "due_journal_id": s.later_journal_id}),
        (
            "link_task_to_contact",
            {"task_id": s.task_id, "contact_id": s.unlinked_contact_id},
        ),
        (
            "unlink_task_from_contact",
            {"task_id": s.task_id, "contact_id": s.contact_id},
        ),
        (
            "attach_intermediate_journal_to_task",
            {"task_id": s.task_id, "journal_id": s.unlinked_journal_id},
        ),
        (
            "detach_intermediate_journal_from_task",
            {"task_id": s.task_id, "journal_id": s.intermediate_journal_id},
        ),
        # Alone on its list and already at the top: a no-op, refused anyway.
        (
            "reorder_list_tasks",
            {"task_list_id": s.task_list_id, "task_ids": [s.task_id]},
        ),
    ]


TOOLS = [
    "set_task_status",
    "update_task",
    "update_task:flag",
    "update_task:icon",
    "update_task:clear-icon",
    "update_task:due-date",
    "update_task:clear-due-date",
    "delete_task",
    "retarget_task",
    "link_task_to_contact",
    "unlink_task_from_contact",
    "attach_intermediate_journal_to_task",
    "detach_intermediate_journal_from_task",
    "reorder_list_tasks",
]


class TestEveryWriteToolRefuses:
    @pytest.mark.parametrize("tool", TOOLS)
    async def test_the_tool_refuses_naming_the_way_out(
        self,
        tool: str,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        seeded: ArchivedListTask,
    ) -> None:
        (arguments,) = [args for name, args in _calls(seeded) if name == tool]
        before = await task_state(clean_database, seeded.task_id)

        async with authenticated_lifespan_client() as client:
            # A case id may name a variant after a colon; the tool is before it.
            response = await _raw_call(client, tool.split(":")[0], arguments)

        refused = extract_mcp_tool_error(response.text)
        assert refused["error"] == "Task error"
        assert "archived" in refused["message"]
        assert "unarchive" in refused["message"]
        assert await task_state(clean_database, seeded.task_id) == before
        assert await task_events(clean_database, task_id=seeded.task_id) == []


class TestCreatingOnAnArchivedListIsRefused:
    """``create_task`` naming an archived list: a create, so it has its own test.

    The table above compares an existing task before and after; a create has no
    task to compare, so this asserts the list gained nothing instead.
    """

    async def test_the_create_is_refused_naming_the_way_out(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        seeded: ArchivedListTask,
    ) -> None:
        before = await count(
            clean_database, COUNT_LIST_TASKS, {"task_list_id": seeded.task_list_id}
        )

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "create_task",
                {"task_list_id": seeded.task_list_id, "text": "pack the spare torch"},
            )

        refused = extract_mcp_tool_error(response.text)
        assert refused["error"] == "Task error"
        assert "archived" in refused["message"]
        assert "unarchive" in refused["message"]
        assert (
            await count(
                clean_database, COUNT_LIST_TASKS, {"task_list_id": seeded.task_list_id}
            )
            == before
        )
        assert [
            event
            for event in await task_events(clean_database)
            if event.event_type == "TaskCreated"
            and event.payload.get("task_list_id") == seeded.task_list_id
        ] == []

    async def test_a_create_due_in_a_past_journal_is_refused_as_archived_first(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        seeded: ArchivedListTask,
    ) -> None:
        """Unarchiving is the way out; correcting the journal would not be."""
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "create_task",
                {
                    "task_list_id": seeded.task_list_id,
                    "due_journal_id": past_id,
                    "text": "pack the spare torch",
                },
            )

        refused = extract_mcp_tool_error(response.text)
        assert refused["error"] == "Task error"
        assert "unarchive" in refused["message"]
        assert "future" not in refused["message"]
        assert [
            event
            for event in await task_events(clean_database)
            if event.event_type == "TaskCreated"
        ] == []


class TestReadsStayOpen:
    async def test_get_task_still_answers(
        self,
        authenticated_lifespan_client: Any,
        seeded: ArchivedListTask,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(client, "get_task", {"task_id": seeded.task_id})

        assert extract_typed_tool_result(response.text)["id"] == seeded.task_id
