"""Unit tests for the task list MCP tools' schemas, as a client sees them.

The fixed icon set and the archived filter reach an agent only through these
schemas, so their enums are asserted against the domain types directly: a key
added to ``TaskIcon`` must appear here without anyone copying it.
"""

from typing import Any

from core_shared.models.tasks import TaskIcon, TaskListArchiveFilter
from fastmcp import Client, FastMCP

from app.mcp.domains.tasks.tools import register_task_tools

_LIST_FIELDS = {
    "id",
    "name",
    "icon",
    "position",
    "archived",
    "archived_at",
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

    async def test_get_takes_only_the_list_id(self) -> None:
        schema = (await _tools())["get_task_list"].input_schema

        assert set(schema["properties"]) == {"task_list_id"}


class TestTheResultShapeIsPublished:
    async def test_create_and_get_answer_with_one_list(self) -> None:
        tools = await _tools()

        for name in ("create_task_list", "get_task_list"):
            schema = tools[name].output_schema
            assert schema is not None, f"{name} publishes no outputSchema"
            assert set(schema["properties"]) == _LIST_FIELDS
            assert _enum_values(schema, schema["properties"]["icon"]) == [
                icon.value for icon in TaskIcon
            ]

    async def test_list_answers_with_lists(self) -> None:
        schema = (await _tools())["list_task_lists"].output_schema

        assert schema is not None
        assert set(schema["properties"]) == {"lists"}
