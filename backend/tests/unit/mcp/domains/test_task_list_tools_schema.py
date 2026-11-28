"""Unit tests for the task list MCP tools' schemas, as a client sees them.

The fixed icon set and the archived filter reach an agent only through these
schemas, so their enums are asserted against the domain types directly: a key
added to ``TaskIcon`` must appear here without anyone copying it.
"""

from typing import Any

from core_shared.models.tasks import TaskIcon, TaskListArchiveFilter
from fastmcp import Client, FastMCP

from app.api.common.identifiers import INT32_MAX
from app.mcp.domains.tasks.tools import register_task_tools

_LIST_FIELDS = {
    "id",
    "name",
    "icon",
    "position",
    "archived",
    "archived_at",
    "associated_journal_id",
    "created_at",
    "updated_at",
}


async def _tools() -> dict[str, Any]:
    mcp: FastMCP[None] = FastMCP(name="Test")
    register_task_tools(mcp)
    async with Client(mcp) as client:
        return {tool.name: tool for tool in await client.list_tools()}


def _enum_values(schema: dict[str, Any], node: dict[str, Any]) -> list[str]:
    """The enum a property allows, through ``$ref`` and a nullable ``anyOf``."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return _enum_values(schema, schema["$defs"][name])
    if "anyOf" in node:
        values: list[str] = []
        for option in node["anyOf"]:
            if option.get("type") != "null":
                values.extend(_enum_values(schema, option))
        return values
    enum: list[str] = node["enum"]
    return enum


def _item(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """A list item's own schema, through a ``$ref``."""
    if "$ref" in node:
        resolved: dict[str, Any] = schema["$defs"][node["$ref"].rsplit("/", 1)[-1]]
        return resolved
    return node


class TestTheInputsAreTyped:
    async def test_create_offers_exactly_the_fixed_icon_set(self) -> None:
        schema = (await _tools())["create_task_list"].input_schema

        assert _enum_values(schema, schema["properties"]["icon"]) == [
            icon.value for icon in TaskIcon
        ]
        assert schema["required"] == ["name"]
        assert "position" not in schema["properties"]

    async def test_list_offers_exactly_the_archived_filters(self) -> None:
        schema = (await _tools())["list_task_lists"].input_schema

        assert _enum_values(schema, schema["properties"]["archived"]) == [
            archived.value for archived in TaskListArchiveFilter
        ]
        assert "required" not in schema or schema["required"] == []

    async def test_list_takes_a_bounded_name_filter_and_opt_in_paging(self) -> None:
        schema = (await _tools())["list_task_lists"].input_schema
        properties = schema["properties"]

        assert set(properties) == {"archived", "name", "paged", "page", "limit"}
        assert [option["type"] for option in properties["name"]["anyOf"]] == [
            "string",
            "null",
        ]
        assert properties["paged"]["type"] == "boolean"
        assert properties["paged"]["default"] is False
        assert (properties["page"]["minimum"], properties["page"]["maximum"]) == (
            1,
            INT32_MAX,
        )
        assert (properties["limit"]["minimum"], properties["limit"]["maximum"]) == (
            1,
            100,
        )
        assert (properties["page"]["default"], properties["limit"]["default"]) == (
            1,
            20,
        )

    async def test_update_offers_the_fixed_icon_set_and_a_clear_flag(self) -> None:
        schema = (await _tools())["update_task_list"].input_schema
        properties = schema["properties"]

        assert set(properties) == {
            "task_list_id",
            "name",
            "icon",
            "clear_icon",
            "associated_journal_id",
            "clear_associated_journal",
        }
        assert schema["required"] == ["task_list_id"]
        assert _enum_values(schema, properties["icon"]) == [
            icon.value for icon in TaskIcon
        ]
        assert properties["clear_icon"]["type"] == "boolean"
        assert properties["clear_icon"]["default"] is False
        assert (
            properties["task_list_id"]["minimum"],
            properties["task_list_id"]["maximum"],
        ) == (1, INT32_MAX)

    async def test_update_takes_a_bounded_journal_id_and_a_clear_flag(self) -> None:
        properties = (await _tools())["update_task_list"].input_schema["properties"]

        [journal_id] = [
            option
            for option in properties["associated_journal_id"]["anyOf"]
            if option.get("type") != "null"
        ]
        assert (journal_id["type"], journal_id["minimum"], journal_id["maximum"]) == (
            "integer",
            1,
            INT32_MAX,
        )
        clear = properties["clear_associated_journal"]
        assert (clear["type"], clear["default"]) == ("boolean", False)

    async def test_get_takes_only_the_list_id(self) -> None:
        schema = (await _tools())["get_task_list"].input_schema

        assert set(schema["properties"]) == {"task_list_id"}

    async def test_move_takes_the_list_and_a_bounded_index(self) -> None:
        schema = (await _tools())["move_task_list"].input_schema

        assert set(schema["properties"]) == {"task_list_id", "index"}
        assert sorted(schema["required"]) == ["index", "task_list_id"]
        index = schema["properties"]["index"]
        assert (index["type"], index["minimum"]) == ("integer", 0)
        assert schema["properties"]["task_list_id"]["minimum"] == 1

    async def test_archive_and_unarchive_take_only_a_bounded_list_id(self) -> None:
        tools = await _tools()

        for name in ("archive_task_list", "unarchive_task_list"):
            schema = tools[name].input_schema
            assert set(schema["properties"]) == {"task_list_id"}, name
            assert schema["required"] == ["task_list_id"], name
            list_id = schema["properties"]["task_list_id"]
            assert (list_id["minimum"], list_id["maximum"]) == (1, INT32_MAX), name

    async def test_archive_and_unarchive_are_idempotent_non_destructive_writes(
        self,
    ) -> None:
        tools = await _tools()

        for name in ("archive_task_list", "unarchive_task_list"):
            annotations = tools[name].annotations
            assert annotations is not None, name
            assert annotations.read_only_hint is False, name
            assert annotations.destructive_hint is False, name
            assert annotations.idempotent_hint is True, name

    async def test_history_takes_a_bounded_list_id_and_a_bounded_page(
        self,
    ) -> None:
        schema = (await _tools())["get_task_list_history"].input_schema
        properties = schema["properties"]

        assert set(properties) == {"task_list_id", "page", "limit"}
        assert schema["required"] == ["task_list_id"]
        assert (
            properties["task_list_id"]["minimum"],
            properties["task_list_id"]["maximum"],
        ) == (1, INT32_MAX)
        assert (properties["page"]["minimum"], properties["page"]["maximum"]) == (
            1,
            INT32_MAX,
        )
        assert (properties["limit"]["minimum"], properties["limit"]["maximum"]) == (
            1,
            100,
        )

    async def test_history_is_read_only(self) -> None:
        annotations = (await _tools())["get_task_list_history"].annotations

        assert annotations is not None
        assert annotations.read_only_hint is True

    async def test_history_names_its_vocabulary(self) -> None:
        """An agent must be able to tell an archive from an unarchive."""
        description = (await _tools())["get_task_list_history"].description or ""

        for term in ("__created__", "name", "icon", "archived_at"):
            assert f"``{term}``" in description, term
        assert "archive" in description
        assert "unarchive" in description


class TestTheResultShapeIsPublished:
    async def test_create_get_and_update_answer_with_one_list(self) -> None:
        tools = await _tools()

        for name in (
            "create_task_list",
            "get_task_list",
            "update_task_list",
            "archive_task_list",
            "unarchive_task_list",
        ):
            schema = tools[name].output_schema
            assert schema is not None, f"{name} publishes no outputSchema"
            assert set(schema["properties"]) == _LIST_FIELDS
            assert _enum_values(schema, schema["properties"]["icon"]) == [
                icon.value for icon in TaskIcon
            ]

    async def test_move_answers_with_lists(self) -> None:
        schema = (await _tools())["move_task_list"].output_schema

        assert schema is not None, "move_task_list publishes no outputSchema"
        assert set(schema["properties"]) == {"lists"}
        item = _item(schema, schema["properties"]["lists"]["items"])
        assert set(item["properties"]) == _LIST_FIELDS

    async def test_the_listing_answers_with_lists_and_their_open_task_counts(
        self,
    ) -> None:
        """The listing carries each list's open-task count; a move does not."""
        schema = (await _tools())["list_task_lists"].output_schema

        assert schema is not None, "list_task_lists publishes no outputSchema"
        assert set(schema["properties"]) == {"lists", "total_count", "paged"}
        assert schema["properties"]["total_count"]["type"] == "integer"
        assert schema["properties"]["paged"]["type"] == "boolean"
        item = _item(schema, schema["properties"]["lists"]["items"])
        assert set(item["properties"]) == _LIST_FIELDS | {"open_task_count"}
        assert item["properties"]["open_task_count"]["type"] == "integer"

    async def test_history_answers_with_a_page_of_entries(self) -> None:
        schema = (await _tools())["get_task_list_history"].output_schema

        assert schema is not None
        assert set(schema["properties"]) == {
            "task_list_id",
            "total_count",
            "page",
            "limit",
            "entries",
        }
        entry = schema["properties"]["entries"]["items"]
        if "$ref" in entry:
            entry = schema["$defs"][entry["$ref"].rsplit("/", 1)[-1]]
        assert set(entry["properties"]) == {
            "field_name",
            "old_value",
            "new_value",
            "changed_by",
            "source",
            "created_at",
        }


class TestTheListTasksRead:
    """``list_task_list_tasks``: a list with its tasks, with the paging an
    agent controls published in the schema it reads."""

    async def test_takes_a_list_id_and_the_paging_options(self) -> None:
        schema = (await _tools())["list_task_list_tasks"].input_schema
        properties = schema["properties"]

        assert set(properties) == {
            "task_list_id",
            "include_completed",
            "page",
            "limit",
            "page_open_tasks",
        }
        assert schema["required"] == ["task_list_id"]
        assert (
            properties["task_list_id"]["minimum"],
            properties["task_list_id"]["maximum"],
        ) == (1, INT32_MAX)
        assert (properties["page"]["minimum"], properties["page"]["maximum"]) == (
            1,
            INT32_MAX,
        )
        assert (properties["limit"]["minimum"], properties["limit"]["maximum"]) == (
            1,
            100,
        )
        assert properties["page"]["default"] == 1
        assert properties["limit"]["default"] == 20
        assert properties["include_completed"]["type"] == "boolean"
        assert properties["include_completed"]["default"] is True
        assert properties["page_open_tasks"]["type"] == "boolean"
        assert properties["page_open_tasks"]["default"] is False

    async def test_is_read_only(self) -> None:
        annotations = (await _tools())["list_task_list_tasks"].annotations

        assert annotations is not None
        assert annotations.read_only_hint is True

    async def test_answers_with_the_list_and_both_sections(self) -> None:
        schema = (await _tools())["list_task_list_tasks"].output_schema

        assert schema is not None, "list_task_list_tasks publishes no outputSchema"
        properties = schema["properties"]
        assert set(properties) == {
            "task_list",
            "page",
            "limit",
            "open_tasks",
            "completed",
        }
        assert set(_item(schema, properties["task_list"])["properties"]) == (
            _LIST_FIELDS
        )
        open_tasks = _item(schema, properties["open_tasks"])
        assert set(open_tasks["properties"]) == {"total_count", "paged", "tasks"}
        (completed_ref,) = [
            option
            for option in properties["completed"]["anyOf"]
            if option.get("type") != "null"
        ]
        completed = _item(schema, completed_ref)
        assert set(completed["properties"]) == {"total_count", "tasks"}
        task = _item(schema, open_tasks["properties"]["tasks"]["items"])
        assert {"task_list", "due_date", "overdue", "flagged", "icon"} <= set(
            task["properties"]
        )

    async def test_describes_the_order_the_paging_and_the_options(self) -> None:
        description = (await _tools())["list_task_list_tasks"].description or ""

        assert "manual order" in description
        assert "most recently closed first" in description
        for option in ("include_completed", "page_open_tasks", "limit", "page"):
            assert f"``{option}``" in description, option


class TestTheDeleteTool:
    """``delete_task_list``: the one destructive list write."""

    async def test_takes_only_a_bounded_list_id(self) -> None:
        schema = (await _tools())["delete_task_list"].input_schema

        assert set(schema["properties"]) == {"task_list_id"}
        assert schema["required"] == ["task_list_id"]
        list_id = schema["properties"]["task_list_id"]
        assert (list_id["type"], list_id["minimum"], list_id["maximum"]) == (
            "integer",
            1,
            INT32_MAX,
        )

    async def test_is_a_destructive_write(self) -> None:
        annotations = (await _tools())["delete_task_list"].annotations

        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is True

    async def test_answers_with_the_deleted_and_kept_task_ids(self) -> None:
        schema = (await _tools())["delete_task_list"].output_schema

        assert schema is not None, "delete_task_list publishes no outputSchema"
        assert set(schema["properties"]) == {
            "deleted",
            "task_list_id",
            "deleted_task_ids",
            "kept_task_ids",
        }
        for key in ("deleted_task_ids", "kept_task_ids"):
            assert schema["properties"][key]["items"]["type"] == "integer", key

    async def test_describes_which_tasks_survive_and_the_archived_refusal(
        self,
    ) -> None:
        """An agent must know what it is about to destroy before it calls."""
        description = (await _tools())["delete_task_list"].description or ""

        assert "both" in description
        assert "journal-only" in description
        assert "archived" in description
        assert "unarchive" in description.lower()
