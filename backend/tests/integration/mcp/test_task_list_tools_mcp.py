"""Integration tests for the task list MCP tools, over the real MCP endpoint.

Covers ``create_task_list``, ``get_task_list``, ``list_task_lists``,
``update_task_list``, ``move_task_list``, ``archive_task_list``,
``unarchive_task_list`` and ``get_task_list_history``.

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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    extract_mcp_tool_error,
    extract_typed_tool_result,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)
from tests.integration.tasks.task_seeding import (
    LIST_LIFE,
    OTHER_USER_ID,
    USER_ID,
    count,
    delete_task_list_row,
    seed_task_list,
    seed_task_list_history,
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


async def _row(conn: AsyncConnection, task_list_id: int) -> dict[str, Any]:
    row = (
        await conn.execute(
            text("SELECT * FROM task_lists WHERE id = :id"), {"id": task_list_id}
        )
    ).one()
    return dict(row._mapping)


class TestUpdateTaskListTool:
    async def test_renames_a_list_and_answers_with_it(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(clean_database, "Packing", icon=TaskIcon.LUGGAGE)

        async with authenticated_lifespan_client() as client:
            updated = await _call(
                client, "update_task_list", task_list_id=seeded.id, name="Trip"
            )

        assert updated["id"] == seeded.id
        assert (updated["name"], updated["icon"], updated["archived"]) == (
            "Trip",
            "luggage",
            False,
        )

    async def test_sets_an_icon_attributed_to_the_assistant(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(clean_database, "Packing")

        async with authenticated_lifespan_client() as client:
            updated = await _call(
                client, "update_task_list", task_list_id=seeded.id, icon="luggage"
            )

        assert (updated["name"], updated["icon"]) == ("Packing", "luggage")
        (event,) = await task_list_events(clean_database, task_list_id=seeded.id)
        assert event.event_type == "TaskListUpdated"
        assert event.payload["changed_fields"] == {"icon": [None, "luggage"]}
        assert (event.payload["source"], event.payload["changed_by"]) == (
            "mcp",
            "mcp",
        )

    async def test_clear_icon_clears_it(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(clean_database, "Packing", icon=TaskIcon.LUGGAGE)
        assert seeded.id is not None

        async with authenticated_lifespan_client() as client:
            updated = await _call(
                client, "update_task_list", task_list_id=seeded.id, clear_icon=True
            )

        assert updated["icon"] is None
        assert (await _row(clean_database, seeded.id))["icon"] is None

    @pytest.mark.parametrize(
        ("arguments", "field"),
        [
            pytest.param({"icon": "luggage", "clear_icon": True}, "icon", id="both"),
            pytest.param({}, "name", id="nothing-named"),
            pytest.param({"name": "   "}, "name", id="blank-name"),
            pytest.param(
                {"name": "x" * (MAX_TASK_LIST_NAME_LENGTH + 1)}, "name", id="long-name"
            ),
        ],
    )
    async def test_a_refused_update_names_the_field_and_writes_nothing(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        arguments: dict[str, Any],
        field: str,
    ) -> None:
        seeded = await seed_task_list(clean_database, "Packing", icon=TaskIcon.LUGGAGE)
        assert seeded.id is not None
        before = await _row(clean_database, seeded.id)

        async with authenticated_lifespan_client() as client:
            refusal = await _refused(
                client, "update_task_list", task_list_id=seeded.id, **arguments
            )

        assert refusal["error"] == "Task error"
        assert field in refusal["message"]
        assert await _row(clean_database, seeded.id) == before
        assert await task_list_events(clean_database) == []

    async def test_an_icon_outside_the_fixed_set_is_refused(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(clean_database, "Packing")
        assert seeded.id is not None
        before = await _row(clean_database, seeded.id)

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "update_task_list",
                {"task_list_id": seeded.id, "icon": "unicorn"},
            )

        # Refused by argument validation, before the tool runs.
        assert '"isError":true' in response.text
        assert "icon" in response.text
        assert await _row(clean_database, seeded.id) == before

    async def test_another_users_list_is_indistinguishable_from_a_missing_one(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(clean_database, "Theirs", user_id=OTHER_USER_ID)
        assert foreign.id is not None
        before = await _row(clean_database, foreign.id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client, "update_task_list", task_list_id=foreign.id, name="Mine"
            )
            missing = await _refused(
                client, "update_task_list", task_list_id=999_999, name="Mine"
            )

        assert refused["error"] == missing["error"] == "Not found"
        assert refused["message"].replace(str(foreign.id), "X") == missing[
            "message"
        ].replace("999999", "X")
        assert "Theirs" not in str(refused)
        assert await _row(clean_database, foreign.id) == before
        assert await task_list_events(clean_database) == []

    async def test_an_archived_list_is_refused_naming_the_way_out(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        archived = await seed_task_list(
            clean_database, "Old trip", archived_at=ARCHIVED_AT
        )
        assert archived.id is not None
        before = await _row(clean_database, archived.id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client, "update_task_list", task_list_id=archived.id, name="Renamed"
            )

        assert refused["error"] == "Task error"
        assert "archived" in refused["message"]
        assert "unarchive" in refused["message"]
        assert await _row(clean_database, archived.id) == before
        assert await task_list_events(clean_database) == []


class TestArchiveTaskListTools:
    """``archive_task_list`` and ``unarchive_task_list``: one list id each."""

    async def test_archive_then_unarchive_round_trips_attributed_to_the_assistant(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(clean_database, "Packing", icon=TaskIcon.LUGGAGE)
        assert seeded.id is not None

        async with authenticated_lifespan_client() as client:
            archived = await _call(client, "archive_task_list", task_list_id=seeded.id)
            listed_active = await _call(client, "list_task_lists")
            restored = await _call(
                client, "unarchive_task_list", task_list_id=seeded.id
            )

        assert archived["archived"] is True
        assert archived["archived_at"] is not None
        assert (archived["name"], archived["icon"]) == ("Packing", "luggage")
        assert listed_active["lists"] == []
        assert (restored["archived"], restored["archived_at"]) == (False, None)
        assert restored["position"] == seeded.position
        archived_event, unarchived_event = await task_list_events(clean_database)
        old, new = archived_event.payload["changed_fields"]["archived_at"]
        assert old is None
        assert datetime.fromisoformat(new) == datetime.fromisoformat(
            archived["archived_at"]
        )
        assert unarchived_event.payload["changed_fields"] == {
            "archived_at": [new, None]
        }
        for event in (archived_event, unarchived_event):
            assert (event.payload["source"], event.payload["changed_by"]) == (
                "mcp",
                "mcp",
            )

    async def test_repeating_either_answers_the_list_and_records_nothing(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        archived = await seed_task_list(
            clean_database, "Old trip", archived_at=ARCHIVED_AT
        )
        active = await seed_task_list(clean_database, "Packing")

        async with authenticated_lifespan_client() as client:
            again = await _call(client, "archive_task_list", task_list_id=archived.id)
            still = await _call(client, "unarchive_task_list", task_list_id=active.id)

        assert datetime.fromisoformat(again["archived_at"]) == ARCHIVED_AT
        assert still["archived"] is False
        assert await task_list_events(clean_database) == []

    @pytest.mark.parametrize("tool", ["archive_task_list", "unarchive_task_list"])
    async def test_another_users_list_is_indistinguishable_from_a_missing_one(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        tool: str,
    ) -> None:
        # Archived for unarchive, so a refusal cannot be a no-op in disguise.
        foreign = await seed_task_list(
            clean_database,
            "Theirs",
            user_id=OTHER_USER_ID,
            archived_at=ARCHIVED_AT if tool == "unarchive_task_list" else None,
        )
        assert foreign.id is not None
        before = await _row(clean_database, foreign.id)

        async with authenticated_lifespan_client() as client:
            refused = await _refused(client, tool, task_list_id=foreign.id)
            missing = await _refused(client, tool, task_list_id=999_999)

        assert refused["error"] == missing["error"] == "Not found"
        assert refused["message"].replace(str(foreign.id), "X") == missing[
            "message"
        ].replace("999999", "X")
        assert "Theirs" not in str(refused)
        assert await _row(clean_database, foreign.id) == before
        assert await task_list_events(clean_database) == []

    @pytest.mark.parametrize("tool", ["archive_task_list", "unarchive_task_list"])
    async def test_an_out_of_range_id_is_refused(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        tool: str,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(client, tool, {"task_list_id": 0})

        assert '"isError":true' in response.text
        # The bound's own refusal, not a lookup of a list that does not exist.
        assert "task_list_id" in response.text
        assert "greater than or equal to 1" in response.text
        assert "not found" not in response.text.lower()


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


_COUNT_OUTBOX = "SELECT COUNT(*) FROM outbox_events"


def _ids(result: dict[str, Any]) -> list[int]:
    return [task_list["id"] for task_list in result["lists"]]


class TestMoveTaskListTool:
    async def test_moves_the_list_and_answers_the_new_order(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        a = (await seed_task_list(clean_database, "A")).id
        b = (await seed_task_list(clean_database, "B")).id
        c = (await seed_task_list(clean_database, "C")).id

        async with authenticated_lifespan_client() as client:
            result = await _call(client, "move_task_list", task_list_id=c, index=0)
            listed = await _call(client, "list_task_lists")

        assert _ids(result) == [c, a, b]
        assert [each["position"] for each in result["lists"]] == [0, 1, 2]
        assert _ids(listed) == [c, a, b]
        assert await count(clean_database, _COUNT_OUTBOX, {}) == 0

    async def test_an_index_past_the_end_moves_the_list_to_the_bottom(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        a = (await seed_task_list(clean_database, "A")).id
        b = (await seed_task_list(clean_database, "B")).id

        async with authenticated_lifespan_client() as client:
            result = await _call(client, "move_task_list", task_list_id=a, index=50)

        assert _ids(result) == [b, a]

    async def test_a_negative_index_is_refused(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        a = (await seed_task_list(clean_database, "A")).id
        b = (await seed_task_list(clean_database, "B")).id

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client, "move_task_list", {"task_list_id": b, "index": -1}
            )
            listed = await _call(client, "list_task_lists")

        assert '"isError":true' in response.text
        assert "index" in response.text
        assert _ids(listed) == [a, b]

    async def test_an_archived_list_is_refused_naming_the_way_out(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        a = (await seed_task_list(clean_database, "A")).id
        archived = await seed_task_list(
            clean_database, "Old trip", archived_at=ARCHIVED_AT
        )

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client, "move_task_list", task_list_id=archived.id, index=0
            )
            listed = await _call(client, "list_task_lists", archived="all")

        assert refused["error"] == "Task error"
        assert "unarchive" in refused["message"].lower()
        assert _ids(listed) == [a, archived.id]

    async def test_another_users_list_is_indistinguishable_from_a_missing_one(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        await seed_task_list(clean_database, "Theirs first", user_id=OTHER_USER_ID)
        foreign = await seed_task_list(clean_database, "Theirs", user_id=OTHER_USER_ID)
        mine = (await seed_task_list(clean_database, "Mine")).id

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client, "move_task_list", task_list_id=foreign.id, index=0
            )
            missing = await _refused(
                client, "move_task_list", task_list_id=999_999, index=0
            )
            listed = await _call(client, "list_task_lists")

        assert refused["error"] == missing["error"] == "Not found"
        assert refused["message"].replace(str(foreign.id), "X") == missing[
            "message"
        ].replace("999999", "X")
        assert "Theirs" not in str(refused)
        assert _ids(listed) == [mine]
        their_order = await clean_database.execute(
            text(
                "SELECT position FROM task_lists WHERE user_id = :user_id "
                "ORDER BY position, id"
            ),
            {"user_id": OTHER_USER_ID},
        )
        assert [row.position for row in their_order] == [0, 1]


class TestIntegerArgumentsAreNotCoerced:
    """fastmcp validates leniently, so without a guard ``true`` would arrive as
    ``1`` and ``"0"`` as ``0`` — acting on a list, or a place, nobody named. The
    REST surface refuses both; so must every task-list tool."""

    @pytest.mark.parametrize(
        "arguments",
        [
            {"index": True},
            {"index": False},
            {"index": "0"},
            {"index": 1.0},
            {"task_list_id": True, "index": 0},
        ],
        ids=repr,
    )
    async def test_a_move_with_a_non_integer_is_refused_and_moves_nothing(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        arguments: dict[str, Any],
    ) -> None:
        a = (await seed_task_list(clean_database, "A")).id
        b = (await seed_task_list(clean_database, "B")).id

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client, "move_task_list", {"task_list_id": b, **arguments}
            )
            listed = await _call(client, "list_task_lists")

        assert '"isError":true' in response.text
        # The guard's own message: a refusal that only came from list 1 not
        # existing would pass the line above without proving anything.
        assert "must be a JSON integer" in response.text
        assert _ids(listed) == [a, b]

    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("get_task_list", {"task_list_id": True}),
            ("get_task_list", {"task_list_id": "1"}),
            ("update_task_list", {"task_list_id": True, "name": "Renamed"}),
            ("archive_task_list", {"task_list_id": True}),
            ("unarchive_task_list", {"task_list_id": "1"}),
        ],
        ids=repr,
    )
    async def test_a_non_integer_list_id_is_refused(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        tool: str,
        arguments: dict[str, Any],
    ) -> None:
        seeded = await seed_task_list(clean_database, "Groceries")

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(client, tool, arguments)
            listed = await _call(client, "list_task_lists")

        assert '"isError":true' in response.text
        assert "must be a JSON integer" in response.text
        assert _names(listed) == [seeded.name]


class TestGetTaskListHistoryTool:
    """The list's record, as an agent reads it: the same rows the REST read
    answers with, the same refusals, from the same service."""

    async def _own_list(
        self, conn: AsyncConnection, *, with_history: bool = True
    ) -> int:
        seeded = await seed_task_list(conn, "Packing")
        assert seeded.id is not None
        if with_history:
            await seed_task_list_history(conn, seeded.id)
        return seeded.id

    async def test_answers_the_whole_life_most_recent_first(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        list_id = await self._own_list(clean_database)

        async with authenticated_lifespan_client() as client:
            result = await _call(client, "get_task_list_history", task_list_id=list_id)

        assert (result["task_list_id"], result["total_count"]) == (list_id, 5)
        assert (result["page"], result["limit"]) == (1, 20)
        assert [
            (e["field_name"], e["old_value"], e["new_value"], e["source"])
            for e in result["entries"]
        ] == [
            (field, old, new, source.value)
            for field, old, new, source in reversed(LIST_LIFE)
        ]
        assert all(e["changed_by"] == e["source"] for e in result["entries"])
        assert all(e["created_at"] for e in result["entries"])

    async def test_an_unprojected_list_answers_empty(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        list_id = await self._own_list(clean_database, with_history=False)

        async with authenticated_lifespan_client() as client:
            result = await _call(client, "get_task_list_history", task_list_id=list_id)

        assert (result["entries"], result["total_count"]) == ([], 0)

    async def test_pages_slice_one_ordering_and_past_the_end_is_empty(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        list_id = await self._own_list(clean_database)

        async with authenticated_lifespan_client() as client:
            second = await _call(
                client, "get_task_list_history", task_list_id=list_id, page=2, limit=2
            )
            beyond = await _call(
                client, "get_task_list_history", task_list_id=list_id, page=9, limit=2
            )

        assert [e["field_name"] for e in second["entries"]] == ["icon", "name"]
        assert (beyond["entries"], beyond["total_count"]) == ([], 5)

    async def test_the_owner_still_reads_it_once_the_row_is_gone(
        self, authenticated_lifespan_client: Any, clean_database: AsyncConnection
    ) -> None:
        list_id = await self._own_list(clean_database)
        await delete_task_list_row(clean_database, list_id)

        async with authenticated_lifespan_client() as client:
            result = await _call(client, "get_task_list_history", task_list_id=list_id)

        assert result["total_count"] == 5

    @pytest.mark.parametrize("with_history", [True, False], ids=["rows", "fallback"])
    async def test_another_users_list_is_indistinguishable_from_a_missing_one(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        with_history: bool,
    ) -> None:
        """Both branches: the other user's rows answer, or their live row does."""
        foreign = await seed_task_list(clean_database, "Theirs", user_id=OTHER_USER_ID)
        assert foreign.id is not None
        if with_history:
            await seed_task_list_history(
                clean_database, foreign.id, user_id=OTHER_USER_ID
            )

        async with authenticated_lifespan_client() as client:
            refused = await _refused(
                client, "get_task_list_history", task_list_id=foreign.id
            )
            missing = await _refused(
                client, "get_task_list_history", task_list_id=999_999
            )

        assert refused["error"] == missing["error"] == "Not found"
        assert refused["message"].replace(str(foreign.id), "X") == missing[
            "message"
        ].replace("999999", "X")
        assert "Theirs" not in str(refused)
        assert "Packing" not in str(refused)

    @pytest.mark.parametrize(
        ("arguments", "refusal"),
        [
            (
                {"task_list_id": 0},
                "task_list_id\\n  Input should be greater than or equal to 1",
            ),
            (
                {"task_list_id": 1, "limit": 101},
                "limit\\n  Input should be less than or equal to 100",
            ),
            (
                {"task_list_id": 1, "page": 0},
                "page\\n  Input should be greater than or equal to 1",
            ),
        ],
    )
    async def test_an_out_of_range_argument_is_refused(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        arguments: dict[str, int],
        refusal: str,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(client, "get_task_list_history", arguments)

        assert '"isError":true' in response.text
        # The argument and its bound, as pydantic words them (JSON-escaped).
        assert refusal in response.text
        assert "not found" not in response.text.lower()
