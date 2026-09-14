"""Tool argument types that hold their shape through fastmcp's validation.

fastmcp validates tool arguments with ``strict=False``, and a runtime
``strict=False`` overrides a field-level ``StrictBool`` — so the transport
would coerce ``"true"`` into ``True``. These tests call a real tool through
``fastmcp.Client`` so they exercise that validation path, not pydantic alone.
"""

from typing import Annotated, Any

import pytest
from fastmcp import Client, FastMCP
from pydantic import Field

from app.mcp.shared.arguments import JsonBool


@pytest.fixture
def server() -> FastMCP[None]:
    mcp: FastMCP[None] = FastMCP("arguments")

    @mcp.tool
    async def confirm(
        confirmed: Annotated[JsonBool, Field(description="Confirms it.")] = False,
    ) -> str:
        return repr(confirmed)

    return mcp


@pytest.mark.parametrize("value", ["true", "yes", 1, "1", 0, None], ids=repr)
async def test_a_non_boolean_is_refused_rather_than_coerced(
    server: FastMCP[None], value: Any
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "confirm", {"confirmed": value}, raise_on_error=False
        )

    assert result.is_error is True


@pytest.mark.parametrize("value", [True, False])
async def test_a_json_boolean_is_accepted_as_itself(
    server: FastMCP[None], value: bool
) -> None:
    async with Client(server) as client:
        result = await client.call_tool("confirm", {"confirmed": value})

    assert result.data == repr(value)


async def test_an_omitted_argument_takes_its_default(server: FastMCP[None]) -> None:
    async with Client(server) as client:
        result = await client.call_tool("confirm", {})

    assert result.data == "False"


async def test_the_schema_still_advertises_a_plain_boolean(
    server: FastMCP[None],
) -> None:
    async with Client(server) as client:
        (tool,) = await client.list_tools()

    assert tool.input_schema["properties"]["confirmed"] == {
        "type": "boolean",
        "default": False,
        "description": "Confirms it.",
    }
