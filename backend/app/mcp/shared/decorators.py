"""
MCP error handling decorators.

Provides decorators for consistent error handling across MCP tools,
reducing duplication and ensuring consistent error responses.
"""

import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import pydantic
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.journals import JournalDomainError, JournalNotFoundError
from core_shared.models.tasks import TaskDomainError

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    DuplicateTagNameError,
    TagNotFoundError,
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
                from pydantic import BaseModel

                # Make kwargs serializable for structlog JSONRenderer
                serializable_kwargs = {}
                for k, v in kwargs.items():
                    if isinstance(v, BaseModel):
                        serializable_kwargs[k] = v.model_dump()
                    else:
                        serializable_kwargs[k] = v

                if operation_type == "search":
                    # Extract search-specific parameters for logging
                    search_kwargs = {
                        k: v
                        for k, v in serializable_kwargs.items()
                        if k in ["query", "limit", "tags", "entity_types", "page"]
                    }
                    MCPLogger.log_operation_start(operation_name, **search_kwargs)
                else:
                    MCPLogger.log_operation_start(operation_name, **serializable_kwargs)

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

            except TagNotFoundError as e:
                # Without this, a missing tag is indistinguishable from a server
                # failure, which callers cannot act on. Mirrors the journal
                # domain handling below. The builder formats the second argument
                # as the id, so pass the id itself rather than the message.
                MCPLogger.log_not_found_error(operation_name, "Tag", e.tag_id)
                return MCPResponseBuilder.not_found_error_response("Tag", e.tag_id)

            except DuplicateTagNameError as e:
                MCPLogger.log_validation_error(operation_name, str(e))
                return MCPResponseBuilder.validation_error_response("name", str(e))

            except JournalNotFoundError as e:
                MCPLogger.log_not_found_error(operation_name, "Journal", str(e))
                return MCPResponseBuilder.not_found_error_response("Journal", str(e))

            except JournalDomainError as e:
                # Handles all journal domain errors including validation errors raised
                # by dataclasses.replace() __post_init__ and UUID parsing errors.
                MCPLogger.log_validation_error(operation_name, e.message)
                if e.status_code == 404:
                    return MCPResponseBuilder.error_response(
                        error_type="Not found",
                        message=e.message,
                    )
                return MCPResponseBuilder.error_response(
                    error_type="Journal error",
                    message=e.message,
                )

            except TaskDomainError as e:
                # Every task rejection is actionable in its own way — pick
                # another journal, pick a later one, say what the commitment is —
                # so the domain's message is passed through rather than being
                # flattened into the catch-all's "an error occurred", which an AI
                # client cannot do anything with. Mirrors the journal handling
                # above, and keeps the tool's answers identical to the REST
                # surface's, where the same errors carry the same text.
                MCPLogger.log_validation_error(operation_name, e.message)
                if e.status_code == 404:
                    return MCPResponseBuilder.error_response(
                        error_type="Not found",
                        message=e.message,
                    )
                return MCPResponseBuilder.error_response(
                    error_type="Task error",
                    message=e.message,
                )

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

            except pydantic.ValidationError as e:
                MCPLogger.log_validation_error(
                    operation_name, f"Schema validation failed: {str(e)}"
                )
                # Extract the first error's field path if available
                errors = e.errors()
                field_name = (
                    ".".join(str(p) for p in errors[0]["loc"])
                    if errors and errors[0].get("loc")
                    else "Input"
                )
                message = errors[0]["msg"] if errors else str(e)
                return MCPResponseBuilder.validation_error_response(field_name, message)

            except ValueError as e:
                MCPLogger.log_validation_error(operation_name, str(e))
                return MCPResponseBuilder.validation_error_response("Input", str(e))

            except Exception as e:  # noqa: BLE001
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
