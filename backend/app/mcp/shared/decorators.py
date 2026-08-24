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
from core_shared.exceptions import PreconditionFailedError
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.journals import (
    JournalDomainError,
    JournalHasAnchoredTasksError,
    JournalNotFoundError,
)
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

            except PreconditionFailedError as e:
                # First, because it is raised from inside both the journal and
                # the contact domains and would otherwise be swallowed by
                # whichever domain branch happened to match. A stale
                # ``expected_version`` is the one refusal a model can fix on its
                # own — re-read, re-apply, retry — but only if it is told that
                # is what happened and which version to retry with. ``code``
                # matches the REST surface's; ``current_version`` matches the
                # tools' ``expected_version`` rather than REST's ``ETag`` naming.
                MCPLogger.log_validation_error(operation_name, e.message)
                return MCPResponseBuilder.error_response(
                    error_type="Conflict",
                    message=e.message,
                    context={
                        "code": "PRECONDITION_FAILED",
                        "resource_type": e.resource_type,
                        "resource_id": str(e.resource_id),
                        "current_version": e.current_etag,
                    },
                )

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

            except JournalHasAnchoredTasksError as e:
                # Above the catch-all below, because this is the one journal
                # refusal an agent is expected to *resolve* rather than report:
                # the specification asks that MCP identify the blocking tasks
                # and the journals that surface them "so an agent can resolve
                # them without going through the UI". The message alone would
                # make it parse English for ids.
                #
                # Same data as the REST surface's ``errors[].meta``, from the
                # same builder, plus the code REST sends so a client can branch
                # on the refusal without matching on prose.
                MCPLogger.log_validation_error(operation_name, e.message)
                return MCPResponseBuilder.error_response(
                    error_type="Journal has anchored tasks",
                    message=e.message,
                    context={"code": "JOURNAL_HAS_ANCHORED_TASKS", **e.error_meta()},
                )

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
                    # Whatever structured detail the error opted into, which for
                    # ``TaskValidationError`` is the field the refusal is about.
                    # Forwarded generically rather than per error type, so the
                    # two surfaces cannot drift: REST renders the same dict as
                    # ``errors[].meta``. The hook's default is ``None`` and
                    # ``error_response`` merges nothing for a falsy context, so
                    # every error that opted into nothing answers byte-for-byte
                    # what it answered before.
                    context=e.error_meta(),
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
