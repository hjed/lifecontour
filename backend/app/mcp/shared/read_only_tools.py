"""Shared helper for building a read-only MCP tool server for AI generation.

Both the contact summary generator and the journal daily summary generator
need to expose the same curated subset of MCP tools to Gemini.  This module
centralises that construction *and* the schema sanitisation required to work
around boolean-schema values that crash google-genai's ``_filter_to_supported_schema``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.genai import types

logger = logging.getLogger(__name__)

# The canonical set of tool names considered safe (read-only) for AI callers.
READ_ONLY_TOOL_NAMES: list[str] = [
    "get_contact",
    "search_contacts",
    "list_contacts",
    "get_journal",
    "search_journals",
    "list_journals",
    "global_search",
]


def sanitize_schema(schema: dict[str, Any]) -> None:
    """Recursively remove boolean schema properties that crash google-genai.

    The google-genai SDK's ``_filter_to_supported_schema`` assumes that
    JSON-Schema keywords like ``additionalProperties`` and ``items`` always
    hold a nested *dict* schema.  FastMCP (via pydantic) legitimately emits
    ``"additionalProperties": false`` which is a *bool*, causing an
    ``AttributeError: 'bool' object has no attribute 'items'``.

    Stripping the boolean values is safe — omitting ``additionalProperties``
    simply falls back to the default (allow any), which is harmless for
    read-only tool schemas.
    """
    if not isinstance(schema, dict):
        return
    for key in ["additionalProperties", "items"]:
        if key in schema and isinstance(schema[key], bool):
            del schema[key]
    for val in schema.values():
        if isinstance(val, dict):
            sanitize_schema(val)
        elif isinstance(val, list):
            for item in val:
                sanitize_schema(item)


async def create_read_only_mcp_server(server_name: str = "AI Generation Tools") -> Any:
    """Create a FastMCP server containing only read-only tools with sanitised schemas.

    Returns a ``FastMCP`` instance ready for use with ``fastmcp.Client``.
    """
    from fastmcp import FastMCP

    from app.mcp.server import create_mcp_server

    main_mcp = create_mcp_server()
    read_only_mcp = FastMCP(server_name)

    for tool_name in READ_ONLY_TOOL_NAMES:
        t = await main_mcp.get_tool(tool_name)
        if t:
            # Sanitize the tool schema before passing it to Gemini
            if hasattr(t, "parameters") and isinstance(t.parameters, dict):
                sanitize_schema(t.parameters)
            read_only_mcp._local_provider.add_tool(t)

    return read_only_mcp


def build_gemini_session_config(
    session: Any, *, temperature: float = 0.3
) -> types.GenerateContentConfigDict:
    """Build the google-genai config for a request that uses a live MCP session.

    Returns the config as a **dict**, NOT a ``GenerateContentConfig`` object.
    google-genai 2.9.0 deep-copies a config passed as an object before use
    (``models.py:8551-8556`` -> ``model_copy(deep=True)``). The config carries
    the live FastMCP ``ClientSession`` as a tool, and deep-copying the session's
    ``_asyncio.Future`` objects raises "cannot pickle '_asyncio.Future' object".
    A dict takes genai's no-deep-copy branch, so the live session survives.

    Both AI summary generators (daily summary and contact summary) share this
    helper so the workaround lives in exactly one place.
    """
    return {"tools": [session], "temperature": temperature}
