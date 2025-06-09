"""
MCP error handling decorators.

Provides decorators for consistent error handling across MCP tools,
reducing duplication and ensuring consistent error responses.
"""

import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
)
from app.mcp.shared.response_builders import MCPLogger, MCPResponseBuilder


def mcp_unified_error_handler(
    operation_name: str,
    operation_type: str = "general",  # "contact", "search", "management", "general"
) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
    """
    Unified decorator for consistent MCP tool error handling across all operation types.

    This decorator provides comprehensive error handling for MCP tools with configurable
    behavior based on the operation type.

    Args:
        operation_name: Name of the operation for logging
        operation_type: Type of operation ("contact", "search", "management", "general")

    Returns:
        Decorated function with unified error handling
    """

    def decorator(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                # Log operation start with appropriate context
                if operation_type == "search":
                    # Extract search-specific parameters for logging
                    search_kwargs = {
                        k: v
                        for k, v in kwargs.items()
                        if k in ["query", "limit", "tags", "entity_types", "page"]
                    }
                    MCPLogger.log_operation_start(operation_name, **search_kwargs)
                else:
                    MCPLogger.log_operation_start(operation_name, **kwargs)

                # Execute the function
                result = await func(*args, **kwargs)

                # Log success
                MCPLogger.log_operation_success(operation_name)

                return result

            except ContactNotFoundError as e:
                MCPLogger.log_not_found_error(operation_name, "Contact", str(e))
                return MCPResponseBuilder.not_found_error_response("Contact", str(e))

            except ContactValidationError as e:
                MCPLogger.log_validation_error(operation_name, str(e))
                return MCPResponseBuilder.validation_error_response(e.field, e.message)

            except json.JSONDecodeError as e:
                MCPLogger.log_validation_error(
                    operation_name, f"Invalid JSON: {str(e)}"
                )
                field_name = (
                    "contact_data" if operation_type == "management" else "JSON"
                )
                return MCPResponseBuilder.validation_error_response(
                    field_name, f"Failed to parse JSON data: {str(e)}"
                )

            except ValueError as e:
                MCPLogger.log_validation_error(operation_name, str(e))
                return MCPResponseBuilder.validation_error_response("Input", str(e))

            except Exception as e:
                # Handle search-specific errors
                if operation_type == "search":
                    search_context = {
                        "query": kwargs.get("query", "unknown"),
                        "limit": kwargs.get("limit", "unknown"),
                    }
                    MCPLogger.log_operation_error(
                        operation_name, str(e), **search_context
                    )
                    return MCPResponseBuilder.error_response(
                        error_type="Search error",
                        message=f"An error occurred while {operation_name}",
                        context=search_context,
                    )
                else:
                    # Handle general errors
                    MCPLogger.log_operation_error(operation_name, str(e))
                    context = (
                        {"operation_type": operation_type}
                        if operation_type != "general"
                        else None
                    )
                    return MCPResponseBuilder.internal_error_response(
                        operation_name, context=context
                    )

        return wrapper

    return decorator
