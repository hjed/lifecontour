"""Helpers for asserting on the refusals MCP tools raise."""

import json
from collections.abc import Awaitable
from typing import Any

import pytest

from app.mcp.shared.response_builders import MCPToolError


async def raised_tool_error(call: Awaitable[object]) -> dict[str, Any]:
    """Await ``call``, expect it to refuse, and return the refusal's payload.

    Also checks the payload is what the client actually receives: the error's
    text is the only thing that crosses the wire.
    """
    with pytest.raises(MCPToolError) as raised:
        await call
    payload = raised.value.payload
    assert json.loads(str(raised.value)) == payload
    return payload
