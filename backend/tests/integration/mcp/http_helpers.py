"""Helpers for mounted MCP HTTP integration tests."""

import json
from collections.abc import Iterable
from typing import Any

import mcp.types as mcp_types

_WRAPPER_KEYS = {
    "annotations",
    "content",
    "id",
    "isError",
    "jsonrpc",
    "result",
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
        return [value, *_collect_nested_json_dicts(value.values())]

    if isinstance(value, list):
        return _collect_nested_json_dicts(value)

    return []


def extract_mcp_json_payload(response_body: Any) -> dict[str, Any]:
    """Extract the application payload from an MCP HTTP response body."""
    for candidate in _iter_json_dicts(response_body):
        if set(candidate).issubset(_WRAPPER_KEYS):
            continue
        return candidate

    raise AssertionError(
        f"Could not find MCP JSON payload in response: {response_body}"
    )


def mcp_headers(session_id: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Host": "localhost",
    }
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return headers


async def initialize_mcp_session(authenticated_client: Any) -> str:
    """Initialize a streamable HTTP MCP session and return the session id."""
    initialize_response = await authenticated_client.post(
        "/mcp-server/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": mcp_types.LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "pytest",
                    "version": "1.0",
                },
            },
        },
        headers=mcp_headers(),
    )
    assert initialize_response.status_code == 200

    session_id = initialize_response.headers.get("mcp-session-id")
    assert isinstance(session_id, str)

    initialized_response = await authenticated_client.post(
        "/mcp-server/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        headers=mcp_headers(session_id),
    )
    assert initialized_response.status_code in {200, 202, 204}

    return session_id
