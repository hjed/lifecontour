"""
Unit tests for MCP shared response builders.

Tests the response building utilities for consistent MCP tool responses.
"""

import json

from pydantic import BaseModel

from app.mcp.shared.response_builders import MCPResponseBuilder


class SampleResponse(BaseModel):
    """Sample response model for testing."""

    id: str
    name: str
    status: str


class TestMCPResponseBuilder:
    """Test MCPResponseBuilder functionality."""

    def test_success_response(self):
        """Test successful response building."""
        # Create sample data
        data = SampleResponse(id="123", name="Test Item", status="active")

        # Build response
        response = MCPResponseBuilder.success_response(data)

        # Verify response format
        assert isinstance(response, str)

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["id"] == "123"
        assert parsed["name"] == "Test Item"
        assert parsed["status"] == "active"

    def test_success_response_formatting(self):
        """Test that success response is properly formatted."""
        data = SampleResponse(id="456", name="Another Test", status="inactive")

        response = MCPResponseBuilder.success_response(data)

        # Verify it's properly indented JSON
        assert "  " in response  # Should have indentation
        assert response.count("\n") > 0  # Should have newlines

    def test_error_response_basic(self):
        """Test basic error response building."""
        response = MCPResponseBuilder.error_response(
            error_type="Test Error", message="Something went wrong"
        )

        # Verify response format
        assert isinstance(response, str)

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Test Error"
        assert parsed["message"] == "Something went wrong"

    def test_error_response_with_context(self):
        """Test error response with additional context."""
        context = {
            "field": "email",
            "value": "invalid-email",
            "code": "VALIDATION_ERROR",
        }

        response = MCPResponseBuilder.error_response(
            error_type="Validation Error",
            message="Invalid email format",
            context=context,
        )

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Validation Error"
        assert parsed["message"] == "Invalid email format"
        assert parsed["field"] == "email"
        assert parsed["value"] == "invalid-email"
        assert parsed["code"] == "VALIDATION_ERROR"

    def test_error_response_without_context(self):
        """Test error response without context."""
        response = MCPResponseBuilder.error_response(
            error_type="Not Found", message="Resource not found", context=None
        )

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Not Found"
        assert parsed["message"] == "Resource not found"
        assert len(parsed) == 2  # Only error and message fields

    def test_not_found_error_response(self):
        """Test not found error response building."""
        response = MCPResponseBuilder.not_found_error_response(
            entity_type="Contact", entity_id=123
        )

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Contact not found"
        assert "ID: 123" in parsed["message"]
        assert parsed["contact_id"] == 123

    def test_validation_error_response(self):
        """Test validation error response building."""
        response = MCPResponseBuilder.validation_error_response(
            field="email", message="Invalid email format"
        )

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Validation error"
        assert parsed["field"] == "email"
        assert "Invalid email format" in parsed["message"]

    def test_internal_error_response_basic(self):
        """Test basic internal error response building."""
        response = MCPResponseBuilder.internal_error_response(operation="get_contact")

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Internal error"
        assert "get_contact" in parsed["message"]

    def test_internal_error_response_with_context(self):
        """Test internal error response with context."""
        context = {
            "operation_type": "contact",
            "retry_count": 3,
            "last_error": "Database timeout",
        }

        response = MCPResponseBuilder.internal_error_response(
            operation="list_contacts", context=context
        )

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Internal error"
        assert "list_contacts" in parsed["message"]
        assert parsed["operation_type"] == "contact"
        assert parsed["retry_count"] == 3
        assert parsed["last_error"] == "Database timeout"

    def test_internal_error_response_without_context(self):
        """Test internal error response without context."""
        response = MCPResponseBuilder.internal_error_response(
            operation="search_contacts", context=None
        )

        # Parse and verify JSON structure
        parsed = json.loads(response)
        assert parsed["error"] == "Internal error"
        assert "search_contacts" in parsed["message"]
        # Should only have error and message fields
        assert "operation_type" not in parsed

    def test_response_formatting_consistency(self):
        """Test that all response types use consistent formatting."""
        # Test success response
        data = SampleResponse(id="1", name="Test", status="ok")
        success_response = MCPResponseBuilder.success_response(data)

        # Test error response
        error_response = MCPResponseBuilder.error_response("Test Error", "Test message")

        # Both should be properly formatted JSON with indentation
        assert "  " in success_response
        assert "  " in error_response
        assert success_response.count("\n") > 0
        assert error_response.count("\n") > 0

    def test_json_serialization_edge_cases(self):
        """Test JSON serialization with edge cases."""
        # Test with special characters
        response = MCPResponseBuilder.error_response(
            error_type="Special Characters",
            message='Error with quotes: "test" and newlines:\ntest',
        )

        # Should be valid JSON
        parsed = json.loads(response)
        assert 'quotes: "test"' in parsed["message"]
        assert "newlines:\ntest" in parsed["message"]

    def test_empty_context_handling(self):
        """Test handling of empty context dictionary."""
        response = MCPResponseBuilder.error_response(
            error_type="Test Error", message="Test message", context={}
        )

        # Parse and verify - empty context should not add extra fields
        parsed = json.loads(response)
        assert len(parsed) == 2  # Only error and message
        assert parsed["error"] == "Test Error"
        assert parsed["message"] == "Test message"
