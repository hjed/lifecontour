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
        name for name, tool in registered_tools.items() if not _is_typed(tool)
    )

    assert not untyped, (
        "these tools must return a single Pydantic response model — not a str, "
        f"list, Optional or union, which fastmcp wraps in {{'result': ...}}: "
        f"{untyped}"
    )
