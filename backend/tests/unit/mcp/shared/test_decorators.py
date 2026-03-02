"""
Unit tests for MCP shared decorators.

Tests the error handling decorators for MCP tools.
"""

import json

import pytest
from core_shared.models.contacts.exceptions import ContactValidationError

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
)
from app.mcp.shared.decorators import mcp_unified_error_handler


class TestMCPUnifiedErrorHandler:
    """Test the unified MCP error handler decorator."""

    @pytest.mark.asyncio
    async def test_successful_operation_contact_type(self):
        """Test successful operation with contact operation type."""

        @mcp_unified_error_handler("test_operation", "contact")
        async def test_function(param1: str) -> str:
            return f"Success: {param1}"

        # Test successful execution
        result = await test_function("test_value")
        assert result == "Success: test_value"

    @pytest.mark.asyncio
    async def test_successful_operation_search_type(self):
        """Test successful operation with search operation type."""

        @mcp_unified_error_handler("test_search", "search")
        async def test_search_function(query: str, limit: int = 10) -> str:
            return f"Search results for: {query}, limit: {limit}"

        # Test successful execution
        result = await test_search_function("test query", limit=20)
        assert result == "Search results for: test query, limit: 20"

    @pytest.mark.asyncio
    async def test_contact_not_found_error(self):
        """Test handling of ContactNotFoundError."""

        @mcp_unified_error_handler("test_operation", "contact")
        async def test_function() -> str:
            raise ContactNotFoundError(123)

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Contact not found"
        assert "123" in response_data["message"]

    @pytest.mark.asyncio
    async def test_contact_validation_error(self):
        """Test handling of ContactValidationError."""

        @mcp_unified_error_handler("test_operation", "contact")
        async def test_function() -> str:
            raise ContactValidationError("email", "Invalid email format")

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Validation error"
        assert response_data["field"] == "email"
        assert "Invalid email format" in response_data["message"]

    @pytest.mark.asyncio
    async def test_json_decode_error_management_type(self):
        """Test handling of JSONDecodeError for management operations."""

        @mcp_unified_error_handler("create_contact", "management")
        async def test_function() -> str:
            raise json.JSONDecodeError("Invalid JSON", "test", 0)

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Validation error"
        assert response_data["field"] == "contact_data"
        assert "Failed to parse JSON data" in response_data["message"]

    @pytest.mark.asyncio
    async def test_json_decode_error_general_type(self):
        """Test handling of JSONDecodeError for general operations."""

        @mcp_unified_error_handler("test_operation", "general")
        async def test_function() -> str:
            raise json.JSONDecodeError("Invalid JSON", "test", 0)

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Validation error"
        assert response_data["field"] == "JSON"
        assert "Failed to parse JSON data" in response_data["message"]

    @pytest.mark.asyncio
    async def test_value_error(self):
        """Test handling of ValueError."""

        @mcp_unified_error_handler("test_operation", "contact")
        async def test_function() -> str:
            raise ValueError("Invalid input value")

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Validation error"
        assert response_data["field"] == "Input"
        assert "Invalid input value" in response_data["message"]

    @pytest.mark.asyncio
    async def test_search_operation_error_handling(self):
        """Test error handling for search operations."""

        @mcp_unified_error_handler("search_contacts", "search")
        async def test_search_function(query: str, limit: int = 10) -> str:
            raise Exception("Search service unavailable")

        # Test error handling - pass parameters as keyword arguments
        result = await test_search_function(query="test", limit=20)

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Search error"
        assert "search_contacts" in response_data["message"]
        assert response_data["query"] == "test"
        assert response_data["limit"] == 20

    @pytest.mark.asyncio
    async def test_general_operation_error_handling(self):
        """Test error handling for general operations."""

        @mcp_unified_error_handler("test_operation", "general")
        async def test_function() -> str:
            raise Exception("Unexpected error")

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Internal error"
        assert "test_operation" in response_data["message"]

    @pytest.mark.asyncio
    async def test_contact_operation_error_handling(self):
        """Test error handling for contact operations with context."""

        @mcp_unified_error_handler("get_contact", "contact")
        async def test_function() -> str:
            raise Exception("Database connection failed")

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Internal error"
        assert "get_contact" in response_data["message"]
        assert response_data["operation_type"] == "contact"

    @pytest.mark.asyncio
    async def test_management_operation_error_handling(self):
        """Test error handling for management operations with context."""

        @mcp_unified_error_handler("create_contact", "management")
        async def test_function() -> str:
            raise Exception("Service unavailable")

        # Test error handling
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Internal error"
        assert "create_contact" in response_data["message"]
        assert response_data["operation_type"] == "management"

    @pytest.mark.asyncio
    async def test_search_parameter_extraction(self):
        """Test that search parameters are properly extracted for logging."""

        @mcp_unified_error_handler("search_operation", "search")
        async def test_function(
            query: str, limit: int, tags: list[str], other_param: str
        ) -> str:
            return "success"

        # Test with search parameters
        result = await test_function(
            query="test", limit=10, tags=["friend"], other_param="ignored"
        )

        assert result == "success"

    @pytest.mark.asyncio
    async def test_default_operation_type(self):
        """Test decorator with default operation type."""

        @mcp_unified_error_handler("test_operation")  # No operation_type specified
        async def test_function() -> str:
            raise Exception("Test error")

        # Test error handling with default type
        result = await test_function()

        # Parse the JSON response
        response_data = json.loads(result)
        assert response_data["error"] == "Internal error"
        assert "test_operation" in response_data["message"]
