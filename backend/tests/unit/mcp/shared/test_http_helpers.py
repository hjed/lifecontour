"""Unit tests for mounted MCP HTTP test helpers."""

import json
from typing import Any

import pytest

from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    extract_mcp_tool_error,
)


def _sse(result: dict[str, Any]) -> str:
    """A streamable-HTTP body carrying one JSON-RPC ``tools/call`` result."""
    message = {"jsonrpc": "2.0", "id": 2, "result": result}
    return f"event: message\ndata: {json.dumps(message)}\n\n"


def _text(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [{"type": "text", "text": json.dumps(payload)}]


class TestExtractMcpJsonPayload:
    """Test mounted MCP response payload extraction."""

    def test_extracts_payload_from_a_wrapped_string_result(self) -> None:
        """A ``-> str`` tool: the payload is JSON inside the text content."""
        payload = {
            "tags": [{"name": "friend"}, {"name": "colleague"}],
            "total_count": 2,
        }
        response_body = _sse(
            {
                "content": _text(payload),
                "structuredContent": {"result": json.dumps(payload)},
                "isError": False,
                "_meta": {"fastmcp": {"wrap_result": True}},
            }
        )

        assert extract_mcp_json_payload(response_body) == payload

    def test_prefers_structured_content_of_a_typed_result(self) -> None:
        """A model whose keys look like envelope keys is still the payload."""
        payload = {"id": 5, "type": "hike"}
        response_body = _sse(
            {
                "content": _text(payload),
                "structuredContent": payload,
                "isError": False,
            }
        )

        assert extract_mcp_json_payload(response_body) == payload

    def test_extracts_payload_from_streamable_http_error_response(self) -> None:
        """It should unwrap the inner JSON payload from mounted error responses."""
        payload = {
            "error": "CONFLICT",
            "message": "Calendar is in use by 1 journal(s)",
        }
        response_body = _sse({"content": _text(payload), "isError": True})

        assert extract_mcp_json_payload(response_body) == payload


class TestExtractMcpToolError:
    """A refusal is only a refusal if the result says ``isError``."""

    def test_returns_the_error_payload(self) -> None:
        payload = {"error": "Tag not found", "message": "No tag exists with ID: 3"}
        response_body = _sse({"content": _text(payload), "isError": True})

        assert extract_mcp_tool_error(response_body) == payload

    def test_rejects_a_success_carrying_error_json(self) -> None:
        """The pre-typed tools returned errors as successes; that must fail."""
        payload = {"error": "Tag not found", "message": "No tag exists with ID: 3"}
        response_body = _sse({"content": _text(payload), "isError": False})

        with pytest.raises(AssertionError, match="isError"):
            extract_mcp_tool_error(response_body)
