"""Every MCP tool must tell a client what it returns.

fastmcp derives a tool's ``outputSchema`` from its return annotation, and the
schema is the only description of the result a client gets: fastmcp strips
``Returns:`` sections out of tool descriptions. A tool annotated ``-> str``, a
list, an ``Optional`` or a union is published as fastmcp's wrapped
``{"result": ...}`` envelope (``x-fastmcp-wrap-result``), which says nothing
about the fields an agent reads. So every tool returns exactly one response
model, which is published as an object schema of its own.

Like ``test_tool_annotations.py``, this assembles the real server and reads the
tools as a client receives them, so it covers both registration patterns.
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from mcp.types import Tool as MCPTool

from app.mcp.server import create_mcp_server

pytestmark = pytest.mark.unit

#: The marker fastmcp sets on a schema it had to wrap in ``{"result": ...}``.
WRAPPED_MARKER = "x-fastmcp-wrap-result"

#: Tools that still return a JSON string, pending conversion to a response
#: model. Only ever shrinks: a new tool returns its model from the start.
UNTYPED_TOOLS = frozenset(
    {
        "accept_contact_suggestion",
        "add_gear_usage_item",
        "add_journal_to_series",
        "analyze_activity_trends",
        "attach_intermediate_journal_to_task",
        "browse_journals_by_date_window",
        "create_calendar",
        "create_gear_item",
        "create_immich_album_for_journal",
        "create_journal_entry",
        "create_journal_route",
        "create_series",
        "create_task",
        "create_template",
        "delete_calendar",
        "delete_journal",
        "delete_journal_route",
        "delete_journal_tag",
        "delete_series",
        "delete_task",
        "detach_intermediate_journal_from_task",
        "dismiss_incomplete_outdoor_activity",
        "dismiss_review_item",
        "get_activity_stats",
        "get_contact_journals",
        "get_daily_summary",
        "get_gear_item",
        "get_journal",
        "get_journal_by_external_id",
        "get_journal_hierarchy",
        "get_journal_history",
        "get_journal_template",
        "get_merge_candidates",
        "get_outdoor_dashboard",
        "get_route_history",
        "get_series",
        "get_strava_athlete_mappings",
        "get_task",
        "get_task_history",
        "get_template",
        "ignore_contact_suggestion",
        "link_journal_to_contact",
        "link_task_to_contact",
        "list_calendars",
        "list_contact_suggestions",
        "list_gear_items",
        "list_immich_conflicts",
        "list_incomplete_outdoor_activities",
        "list_integrations",
        "list_journal_routes",
        "list_journal_tags",
        "list_journal_tasks",
        "list_journal_types",
        "list_review_items",
        "list_series",
        "list_upcoming_tasks",
        "merge_journal_tag",
        "merge_journals",
        "merge_series",
        "preview_series_merge",
        "remove_gear_usage_item",
        "remove_journal_from_series",
        "resolve_immich_conflict",
        "retarget_task",
        "search_activities",
        "search_immich_photos_for_journal",
        "search_journals",
        "search_templates",
        "set_task_status",
        "trigger_sync",
        "undismiss_incomplete_outdoor_activity",
        "unignore_contact_suggestion",
        "unlink_task_from_contact",
        "update_calendar",
        "update_gear_item",
        "update_journal_entry",
        "update_journal_route",
        "update_journal_tag",
        "update_series",
        "update_task_text",
        "update_template",
    }
)


@pytest.fixture
async def registered_tools() -> dict[str, MCPTool]:
    """Every tool on the real server, as an MCP client receives it."""
    async with Client(create_mcp_server()) as client:
        return {tool.name: tool for tool in await client.list_tools()}


def _is_typed(tool: MCPTool) -> bool:
    schema = tool.output_schema
    return (
        schema is not None
        and schema.get("type") == "object"
        and not schema.get(WRAPPED_MARKER)
    )


def test_every_tool_publishes_an_output_schema(
    registered_tools: dict[str, MCPTool],
) -> None:
    """A return annotation fastmcp cannot resolve publishes no schema at all.

    It fails quietly — a debug log line — so it is asserted on its own.
    """
    missing = sorted(
        name for name, tool in registered_tools.items() if tool.output_schema is None
    )

    assert not missing, (
        "these tools publish no outputSchema; check their return annotation "
        f"is importable at runtime (not only under TYPE_CHECKING): {missing}"
    )


def test_every_tool_returns_one_response_model(
    registered_tools: dict[str, MCPTool],
) -> None:
    untyped = sorted(
        name
        for name, tool in registered_tools.items()
        if name not in UNTYPED_TOOLS and not _is_typed(tool)
    )

    assert not untyped, (
        "these tools must return a single Pydantic response model — not a str, "
        f"list, Optional or union, which fastmcp wraps in {{'result': ...}}: "
        f"{untyped}"
    )


def test_the_untyped_allowlist_is_not_stale(
    registered_tools: dict[str, MCPTool],
) -> None:
    """A converted or removed tool must leave the allowlist with it."""
    converted = sorted(
        name
        for name in UNTYPED_TOOLS & registered_tools.keys()
        if _is_typed(registered_tools[name])
    )
    removed = sorted(UNTYPED_TOOLS - registered_tools.keys())

    assert not converted, f"remove these typed tools from UNTYPED_TOOLS: {converted}"
    assert not removed, f"UNTYPED_TOOLS names tools that do not exist: {removed}"
