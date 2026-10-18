"""Helpers for mounted MCP HTTP integration tests."""

import json
from collections.abc import Iterable
from typing import Any

from mcp.shared.inbound import (
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    MCP_PROTOCOL_VERSION_HEADER,
)
from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

MCP_PATH = "/mcp-server/mcp"

#: The sessionless protocol: no ``initialize`` handshake and no session id —
#: every request carries its own version and client capabilities.
SESSIONLESS_PROTOCOL_VERSION = MODERN_PROTOCOL_VERSIONS[-1]

_CLIENT_INFO = {"name": "pytest", "version": "1.0"}

_WRAPPER_KEYS = {
    "_meta",
    "annotations",
    "content",
    "id",
    "isError",
    "jsonrpc",
    "result",
    # Sessionless (2026-07-28) results say whether they are final or ask for input.
    "resultType",
    "role",
    "structuredContent",
    "text",
    "type",
}


def _load_json(value: str) -> tuple[bool, Any]:
    try:
        return True, json.loads(value)
    except json.JSONDecodeError:
        return False, None


def _collect_nested_json_dicts(values: Iterable[Any]) -> list[dict[str, Any]]:
    nested_dicts: list[dict[str, Any]] = []
    for nested_value in values:
        nested_dicts.extend(_iter_json_dicts(nested_value))
    return nested_dicts


def _iter_sse_json_dicts(value: str) -> list[dict[str, Any]]:
    dicts: list[dict[str, Any]] = []
    for line in value.splitlines():
        if not line.startswith("data:"):
            continue

        loaded, parsed_line = _load_json(line.removeprefix("data:").strip())
        if loaded:
            dicts.extend(_iter_json_dicts(parsed_line))
    return dicts


def _iter_json_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        loaded, parsed_value = _load_json(value)
        if loaded:
            return _iter_json_dicts(parsed_value)
        return _iter_sse_json_dicts(value)

    if isinstance(value, dict):
        # Exclude _meta values from recursion — fastmcp 3.2+ injects
        # metadata dicts (e.g. {"fastmcp": {"wrap_result": true}}) that
        # would otherwise be mistaken for application payloads.
        child_values = [v for k, v in value.items() if k != "_meta"]
        return [value, *_collect_nested_json_dicts(child_values)]

    if isinstance(value, list):
        return _collect_nested_json_dicts(value)

    return []


def _tool_call_result(response_body: Any) -> dict[str, Any] | None:
    """The JSON-RPC ``result`` of a ``tools/call`` response, if there is one."""
    for candidate in _iter_json_dicts(response_body):
        result = candidate.get("result")
        if "jsonrpc" in candidate and isinstance(result, dict):
            return result
    return None


def _typed_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    """A typed tool's ``structuredContent``: the response model itself.

    Read directly rather than by the key heuristic below, which would skip a
    model whose fields happen to share envelope names (``id``, ``type``). A
    ``-> str`` tool's content is wrapped in ``{"result": ...}`` and flagged as
    such in ``_meta``; its payload is the JSON in the text content instead.
    """
    structured = result.get("structuredContent")
    wrapped = result.get("_meta", {}).get("fastmcp", {}).get("wrap_result", False)
    if isinstance(structured, dict) and not wrapped:
        return structured
    return None


def extract_mcp_json_payload(response_body: Any) -> dict[str, Any]:
    """Extract the application payload from an MCP HTTP response body."""
    result = _tool_call_result(response_body)
    if result is not None and not result.get("isError"):
        typed = _typed_payload(result)
        if typed is not None:
            return typed

    for candidate in _iter_json_dicts(response_body):
        if set(candidate).issubset(_WRAPPER_KEYS):
            continue
        return candidate

    raise AssertionError(
        f"Could not find MCP JSON payload in response: {response_body}"
    )


def mcp_headers() -> dict[str, str]:
    """The streamable-HTTP headers every MCP request sends, whatever its era."""
    return {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Host": "localhost",
    }


def sessionless_mcp_headers(method: str, name: str | None = None) -> dict[str, str]:
    """Headers for a sessionless request.

    The protocol version, method and — for a named target such as a tool —
    the name travel as headers so gateways can route without reading the
    body; the server rejects a request whose headers contradict its body.
    """
    headers = {
        **mcp_headers(),
        MCP_PROTOCOL_VERSION_HEADER: SESSIONLESS_PROTOCOL_VERSION,
        MCP_METHOD_HEADER: method,
    }
    if name is not None:
        headers[MCP_NAME_HEADER] = name
    return headers


def sessionless_mcp_request(
    method: str, params: dict[str, Any], *, request_id: int = 1
) -> dict[str, Any]:
    """A JSON-RPC body carrying the per-request envelope in ``params._meta``."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            **params,
            "_meta": {
                PROTOCOL_VERSION_META_KEY: SESSIONLESS_PROTOCOL_VERSION,
                CLIENT_CAPABILITIES_META_KEY: {},
                CLIENT_INFO_META_KEY: _CLIENT_INFO,
            },
        },
    }


async def post_mcp_tool(
    authenticated_client: Any,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    request_id: int = 1,
) -> Any:
    """Call one MCP tool as a sessionless client and return the raw response.

    For tests that inspect the HTTP response itself — a refusal's text, an
    ``isError`` body. Tests that only need the tool's payload use
    ``call_mcp_tool``.
    """
    return await authenticated_client.post(
        MCP_PATH,
        json=sessionless_mcp_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            request_id=request_id,
        ),
        headers=sessionless_mcp_headers("tools/call", tool_name),
    )


async def call_mcp_tool(
    authenticated_client: Any,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    request_id: int = 1,
) -> dict[str, Any]:
    """Call one MCP tool as a sessionless client and return its payload.

    Every mounted-MCP test builds the same ``tools/call`` request, so it lives
    here rather than being copied per test. A refusal fails the call: a test
    that expects one uses ``call_mcp_tool_error``, which asserts it.
    """
    response = await post_mcp_tool(
        authenticated_client, tool_name, arguments, request_id=request_id
    )
    assert response.status_code == 200, response.text
    result = _tool_call_result(response.text)
    assert result is None or not result.get("isError"), (
        f"{tool_name} refused: {response.text}"
    )
    return extract_mcp_json_payload(response.text)


def extract_typed_tool_result(response_body: Any) -> dict[str, Any]:
    """A typed tool's success, checked as a client that reads either half sees it.

    The ``structuredContent`` is the response model and the text content is the
    fallback for clients that ignore it; the two must agree.
    """
    result = _tool_call_result(response_body)
    assert result is not None, f"no tools/call result in: {response_body}"
    assert not result.get("isError"), f"expected a success: {response_body}"
    typed = _typed_payload(result)
    assert typed is not None, f"not a typed result: {response_body}"
    [text] = [block["text"] for block in result["content"]]
    assert json.loads(text) == typed
    return typed


def extract_mcp_tool_error(response_body: Any) -> dict[str, Any]:
    """Extract a refusal's payload, asserting the result is flagged ``isError``.

    A refusal returned as a success would be read by a client as a result, so
    the flag is part of what an error test asserts.
    """
    result = _tool_call_result(response_body)
    assert result is not None, f"no tools/call result in: {response_body}"
    assert result.get("isError") is True, (
        f"expected an isError result, got a success: {response_body}"
    )
    return extract_mcp_json_payload(response_body)


async def call_mcp_tool_error(
    authenticated_client: Any,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    request_id: int = 1,
) -> dict[str, Any]:
    """Call one MCP tool that is expected to refuse, and return the refusal."""
    response = await post_mcp_tool(
        authenticated_client, tool_name, arguments, request_id=request_id
    )
    assert response.status_code == 200, response.text
    return extract_mcp_tool_error(response.text)
