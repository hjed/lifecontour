"""
Unit tests for MCP shared response builders.

Tools return their response model and *raise* a refusal: ``MCPErrors`` builds
the ``MCPToolError`` that fastmcp sends as an ``isError`` result, whose text is
the JSON payload an agent reads the error's ``code`` and context from.
"""

import json
import logging

from fastmcp.exceptions import ToolError
from pydantic import BaseModel

from app.mcp.shared.response_builders import (
    MCPErrors,
    MCPResponseBuilder,
    MCPToolError,
)


class SampleResponse(BaseModel):
    """Sample response model for testing."""

    id: str
    name: str
    status: str


class TestMCPToolError:
    """The exception a refusal travels in."""

    def test_it_is_a_fastmcp_tool_error(self) -> None:
        """fastmcp passes a ToolError through unmasked as ``isError: true``."""
        assert isinstance(MCPToolError({"error": "x", "message": "y"}), ToolError)

    def test_its_text_is_the_json_payload(self) -> None:
        """The text is all a client receives, so it carries the whole payload."""
        error = MCPToolError({"error": "Conflict", "message": "m", "code": "C"})

        assert json.loads(str(error)) == error.payload
        assert error.payload == {"error": "Conflict", "message": "m", "code": "C"}

    def test_its_text_matches_the_previous_wire_format(self) -> None:
        """Byte-identical to the JSON the tools used to return."""
        payload = {"error": "Not found", "message": "gone"}

        assert str(MCPToolError(payload)) == json.dumps(payload, indent=2)

    def test_it_is_logged_as_a_warning(self) -> None:
        """A refusal is expected traffic, not a server fault."""
        assert MCPToolError({"error": "x", "message": "y"}).log_level == logging.WARNING

    def test_special_characters_survive(self) -> None:
        error = MCPErrors.error("Special", 'quotes: "test" and newlines:\ntest')

        parsed = json.loads(str(error))
        assert 'quotes: "test"' in parsed["message"]
        assert "newlines:\ntest" in parsed["message"]


class TestMCPErrors:
    """The refusal factories, one per kind of error."""

    def test_error_without_context(self) -> None:
        error = MCPErrors.error("Not Found", "Resource not found")

        assert error.payload == {"error": "Not Found", "message": "Resource not found"}

    def test_error_merges_context(self) -> None:
        error = MCPErrors.error(
            "Validation Error",
            "Invalid email format",
            context={"field": "email", "code": "VALIDATION_ERROR"},
        )

        assert error.payload == {
            "error": "Validation Error",
            "message": "Invalid email format",
            "field": "email",
            "code": "VALIDATION_ERROR",
        }

    def test_empty_context_adds_nothing(self) -> None:
        error = MCPErrors.error("Test Error", "Test message", context={})

        assert error.payload == {"error": "Test Error", "message": "Test message"}

    def test_not_found(self) -> None:
        error = MCPErrors.not_found("Contact", 123)

        assert error.payload == {
            "error": "Contact not found",
            "message": "No contact exists with ID: 123",
            "contact_id": 123,
        }

    def test_validation(self) -> None:
        error = MCPErrors.validation("email", "Invalid email format")

        assert error.payload == {
            "error": "Validation error",
            "message": "Validation failed for email: Invalid email format",
            "field": "email",
        }

    def test_internal_without_context(self) -> None:
        error = MCPErrors.internal("search_contacts")

        assert error.payload == {
            "error": "Internal error",
            "message": "An error occurred while search_contacts",
        }

    def test_internal_with_context(self) -> None:
        error = MCPErrors.internal("list_contacts", context={"operation_type": "c"})

        assert error.payload["error"] == "Internal error"
        assert error.payload["operation_type"] == "c"


class TestLegacyStringBuilders:
    """Kept only until every tool raises; they render the same payloads."""

    def test_success_response_is_indented_json(self) -> None:
        data = SampleResponse(id="123", name="Test Item", status="active")

        response = MCPResponseBuilder.success_response(data)

        assert json.loads(response) == data.model_dump(mode="json")
        assert response == json.dumps(data.model_dump(mode="json"), indent=2)

    def test_error_builders_render_the_raised_payloads(self) -> None:
        assert MCPResponseBuilder.error_response("E", "m", {"k": 1}) == str(
            MCPErrors.error("E", "m", {"k": 1})
        )
        assert MCPResponseBuilder.validation_error_response("f", "m") == str(
            MCPErrors.validation("f", "m")
        )
        assert MCPResponseBuilder.not_found_error_response("Tag", 3) == str(
            MCPErrors.not_found("Tag", 3)
        )
        assert MCPResponseBuilder.internal_error_response("op") == str(
            MCPErrors.internal("op")
        )
