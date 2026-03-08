"""Unit tests for mounted MCP HTTP test helpers."""

import json

from tests.integration.mcp.http_helpers import extract_mcp_json_payload


class TestExtractMcpJsonPayload:
    """Test mounted MCP response payload extraction."""

    def test_extracts_payload_from_streamable_http_success_response(self) -> None:
        """It should unwrap the inner JSON payload from mounted success responses."""
        payload = {
            "tags": [{"name": "friend"}, {"name": "colleague"}],
            "total_count": 2,
        }
        response_body = (
            "event: message\n"
            f"data: {json.dumps({'jsonrpc': '2.0', 'id': 2, 'result': {'content': [{'type': 'text', 'text': json.dumps(payload)}], 'structuredContent': {'result': json.dumps(payload)}, 'isError': False}})}\n\n"
        )

        assert extract_mcp_json_payload(response_body) == payload

    def test_extracts_payload_from_streamable_http_error_response(self) -> None:
        """It should unwrap the inner JSON payload from mounted error responses."""
        payload = {
            "error": "CONFLICT",
            "message": "Calendar is in use by 1 journal(s)",
        }
        response_body = (
            "event: message\n"
            f"data: {json.dumps({'jsonrpc': '2.0', 'id': 2, 'result': {'content': [{'type': 'text', 'text': json.dumps(payload)}], 'isError': True}})}\n\n"
        )

        assert extract_mcp_json_payload(response_body) == payload
