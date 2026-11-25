"""Integration tests for a task's due journal through MCP ``update_task``.

Over the real MCP endpoint: an agent sets, changes and clears a list task's
due journal with ``due_journal_id`` and ``clear_due_journal``, and moves a
journal-only task's with the same argument under the retarget's rules. Each
refusal reaches it as an actionable error with nothing written, and another
user's task or journal reads as an absent one. The rules and the races are
proved against the service in
``tests/integration/tasks/test_task_service_due_journal_integration.py``.
"""

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
    stored_status,
    task_events,
    task_state,
)

pytestmark = pytest.mark.integration


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


async def _journals(repo: SqlJournalRepository) -> tuple[int, int]:
    first = await create_journal(repo, title="Beach weekend", days_offset=7)
    second = await create_journal(repo, title="Hike", days_offset=14)
    return first, second


class TestAListTask:
    @pytest.mark.parametrize("change", ["set", "changed", "cleared"])
    async def test_the_change_is_stored_and_announced_from_mcp(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        change: str,
    ) -> None:
        old_id, new_id = await _journals(journal_repository)
        cases: dict[str, tuple[int | None, dict[str, Any], int | None]] = {
            "set": (None, {"due_journal_id": new_id}, new_id),
            "changed": (old_id, {"due_journal_id": new_id}, new_id),
            "cleared": (old_id, {"clear_due_journal": True}, None),
        }
        before, arguments, after = cases[change]
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(
            clean_database, task_list_id=list_id, due_journal_id=before
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task(client, task_id=task_id, **arguments)

        assert "error" not in payload
        assert payload["due_journal_id"] == after
        assert payload["intermediate_journal_ids"] == (
            [] if before is None else [before]
        )
        event = (await task_events(clean_database, task_id=task_id))[-1]
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"due_journal_id": [before, after]}
        assert (event.payload["source"], event.payload["changed_by"]) == (
            "mcp",
            "mcp",
        )

    async def test_a_done_task_moves_and_stays_done(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        old_id, new_id = await _journals(journal_repository)
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(
            clean_database,
            task_list_id=list_id,
            due_journal_id=old_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task(client, task_id=task_id, due_journal_id=new_id)

        assert (payload["status"], payload["due_journal_id"]) == ("done", new_id)
        assert await stored_status(clean_database, task_id) == "done"

    async def test_an_explicit_null_journal_is_absent_beside_another_edit(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(
            clean_database, task_list_id=list_id, due_journal_id=journal_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task(
                client, task_id=task_id, text="Reworded", due_journal_id=None
            )

        assert (payload["text"], payload["due_journal_id"]) == ("Reworded", journal_id)


class TestAJournalOnlyTask:
    async def test_a_done_one_is_reopened_with_the_acknowledgement(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        new_id = await create_journal(journal_repository, days_offset=21)
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task(
                client, task_id=task_id, due_journal_id=new_id, acknowledge_reopen=True
            )

        assert (payload["status"], payload["due_journal_id"]) == ("not_done", new_id)
        assert payload["intermediate_journal_ids"] == [due_id]
        assert [
            event.event_type
            for event in await task_events(clean_database, task_id=task_id)
        ] == ["TaskJournalLinked", "TaskDueJournalRetargeted"]

    async def test_a_done_one_without_it_is_refused_naming_the_argument(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        new_id = await create_journal(journal_repository, days_offset=21)
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )
        before = await task_state(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, task_id=task_id, due_journal_id=new_id)

        assert "reopen" in refused["message"].lower()
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []

    async def test_its_due_journal_cannot_be_cleared(
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
            refused = await _refused(client, task_id=task_id, clear_due_journal=True)

        assert refused["error"] == "Task error"
        assert "not cleared" in refused["message"]
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []


class TestRefusals:
    async def test_a_journal_that_is_not_future_is_refused_naming_the_rule(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        past_id = await create_journal(journal_repository, days_offset=-3)
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(clean_database, task_list_id=list_id)
        before = await task_state(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, task_id=task_id, due_journal_id=past_id)

        assert "future" in refused["message"].lower()
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []

    async def test_a_journal_and_its_clear_together_are_refused(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(clean_database, task_list_id=list_id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client,
                task_id=task_id,
                due_journal_id=journal_id,
                clear_due_journal=True,
            )

        assert "not both" in refused["message"]
        assert await task_events(clean_database, task_id=task_id) == []

    async def test_a_date_and_a_journal_together_are_refused_naming_the_date(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(clean_database, task_list_id=list_id)
        before = await task_state(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client,
                task_id=task_id,
                due_journal_id=journal_id,
                due_date="2099-12-31",
            )

        assert refused["error"] == "Task error"
        assert refused["field"] == "due_date"
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []

    @pytest.mark.parametrize("value", ["7", 7.5], ids=["string", "float"])
    async def test_a_journal_id_that_is_not_a_json_integer_is_refused(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        value: object,
    ) -> None:
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(clean_database, task_list_id=list_id)
        before = await task_state(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client, {"task_id": task_id, "due_journal_id": value}
            )

        assert '"isError":true' in response.text
        assert "must be a JSON integer" in response.text
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []


class TestAnotherUsersRows:
    async def test_their_journal_is_not_found_and_nothing_is_written(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        theirs = await create_journal(
            journal_repository, days_offset=7, user_id=OTHER_USER_ID
        )
        list_id = await seed_task_list_id(clean_database)
        task_id = await create_list_task(clean_database, task_list_id=list_id)
        before = await task_state(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, task_id=task_id, due_journal_id=theirs)

        assert refused["error"] == "Not found"
        assert await task_state(clean_database, task_id) == before
        assert await task_events(clean_database, task_id=task_id) == []

    async def test_their_task_is_not_found_and_left_alone(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        foreign_list = await seed_task_list_id(clean_database, user_id=OTHER_USER_ID)
        foreign_task = await create_list_task(
            clean_database, task_list_id=foreign_list, user_id=OTHER_USER_ID
        )
        before = await task_state(clean_database, foreign_task)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client, task_id=foreign_task, due_journal_id=journal_id
            )
            absent = await _refused(client, task_id=999_999, due_journal_id=journal_id)

        assert refused["error"] == absent["error"] == "Not found"
        assert await task_state(clean_database, foreign_task) == before
        assert await task_events(clean_database, task_id=foreign_task) == []
