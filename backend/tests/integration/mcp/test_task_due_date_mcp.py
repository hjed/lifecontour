"""Integration tests for a list task's due date through MCP ``update_task``.

ITER21-001 Phase 22, over the real MCP endpoint: an agent sets, changes and
clears a list task's due date with ``due_date`` and ``clear_due_date``, each
refusal reaches it as an actionable error with nothing written, and another
user's task reads as an absent one. The rules — "today" in the user's timezone
included — are proved against the service in
``tests/integration/tasks/test_task_service_due_date_integration.py``.
"""

import re
from datetime import date
from typing import Any

import pytest
from core_shared.models.tasks import TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    extract_mcp_tool_error,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    create_journal,
    create_list_task,
    create_task,
    seed_task_list_id,
    stored_due_date,
    stored_status,
    task_events,
    task_state,
)

pytestmark = pytest.mark.integration

FUTURE = date(2099, 12, 31)
PAST = date(2000, 1, 1)


async def _raw_call(client: Any, arguments: dict[str, Any]) -> Any:
    response = await client.post(
        "/mcp-server/mcp",
        json=sessionless_mcp_request(
            "tools/call", {"name": "update_task", "arguments": arguments}
        ),
        headers=sessionless_mcp_headers("tools/call", "update_task"),
    )
    assert response.status_code == 200
    return response


async def _update_task(client: Any, **arguments: Any) -> dict[str, Any]:
    return extract_mcp_json_payload((await _raw_call(client, arguments)).text)


async def _refused(client: Any, **arguments: Any) -> dict[str, Any]:
    return extract_mcp_tool_error((await _raw_call(client, arguments)).text)


class TestSetChangeAndClear:
    @pytest.mark.parametrize(
        ("before", "arguments", "after", "pair"),
        [
            (None, {"due_date": "2099-12-31"}, FUTURE, [None, "2099-12-31"]),
            (
                FUTURE,
                {"due_date": "2100-01-15"},
                date(2100, 1, 15),
                ["2099-12-31", "2100-01-15"],
            ),
            (FUTURE, {"clear_due_date": True}, None, ["2099-12-31", None]),
        ],
        ids=["set", "changed", "cleared"],
    )
    async def test_the_change_is_stored_and_announced_from_mcp(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        before: date | None,
        arguments: dict[str, Any],
        after: date | None,
        pair: list[str | None],
    ) -> None:
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(
            clean_database, task_list_id=list_id, due_date=before
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task(client, task_id=task_id, **arguments)

        assert "error" not in payload
        assert payload["due_date"] == (None if after is None else after.isoformat())
        assert payload["status"] == "not_done"
        assert await stored_due_date(clean_database, task_id) == after
        (event,) = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"due_date": pair}
        assert (event.payload["source"], event.payload["changed_by"]) == (
            "mcp",
            "mcp",
        )

    async def test_a_done_task_is_redated_and_stays_done(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(
            clean_database, task_list_id=list_id, status=TaskStatus.DONE
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task(client, task_id=task_id, due_date="2099-12-31")

        assert payload["status"] == "done"
        assert await stored_status(clean_database, task_id) == "done"
        assert await stored_due_date(clean_database, task_id) == FUTURE

    async def test_a_task_due_in_a_journal_has_it_replaced_by_the_date(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Invariant 4, by replacement: the journal left becomes intermediate."""
        journal_id = await create_journal(journal_repository, days_offset=7)
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(
            clean_database, task_list_id=list_id, due_journal_id=journal_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task(client, task_id=task_id, due_date="2099-12-31")

        assert "error" not in payload
        assert (payload["due_date"], payload["due_journal_id"]) == ("2099-12-31", None)
        assert payload["intermediate_journal_ids"] == [journal_id]
        assert await stored_due_date(clean_database, task_id) == FUTURE


class TestRefusals:
    async def test_a_past_date_names_the_rule_and_today(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(clean_database, task_list_id=list_id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, task_id=task_id, due_date="2000-01-01")

        assert refused["error"] == "Task error"
        assert "2000-01-01 is before today" in refused["message"]
        assert re.search(r"today \(\d{4}-\d{2}-\d{2}\)", refused["message"])
        assert "today or later" in refused["message"]
        assert await stored_due_date(clean_database, task_id) is None
        assert await task_events(clean_database, task_id=task_id) == []

    @pytest.mark.parametrize(
        ("arguments", "field"),
        [
            ({"due_date": "2099-12-31", "clear_due_date": True}, "due_date"),
            ({"due_date": 20991231}, "due_date"),
            ({"due_date": "31/12/2099"}, "due_date"),
            ({"clear_due_date": "true"}, "clear_due_date"),
        ],
        ids=["date-and-clear", "numeric-date", "local-format", "string-clear"],
    )
    async def test_a_malformed_call_is_refused_and_changes_nothing(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        arguments: dict[str, Any],
        field: str,
    ) -> None:
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(
            clean_database, task_list_id=list_id, due_date=FUTURE
        )
        before = await task_state(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(client, {"task_id": task_id, **arguments})

        assert '"isError":true' in response.text
        assert field in response.text
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []

    async def test_a_journal_only_task_takes_no_due_date(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        before = await task_state(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, task_id=task_id, due_date="2099-12-31")

        assert refused["error"] == "Task error"
        assert "list" in refused["message"]
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []


class TestAnotherUsersTask:
    async def test_is_not_found_and_left_alone(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        foreign_list = await seed_task_list_id(clean_database, user_id=OTHER_USER_ID)
        foreign_task = await create_list_task(
            clean_database,
            task_list_id=foreign_list,
            due_date=FUTURE,
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, task_id=foreign_task, clear_due_date=True)
            absent = await _refused(client, task_id=999_999, clear_due_date=True)

        assert refused["error"] == absent["error"] == "Not found"
        assert await stored_due_date(clean_database, foreign_task) == FUTURE
        assert await task_events(clean_database, task_id=foreign_task) == []
