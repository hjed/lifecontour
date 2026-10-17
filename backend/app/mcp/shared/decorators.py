"""
MCP error handling decorators.

Provides decorators for consistent error handling across MCP tools,
reducing duplication and ensuring consistent error responses.
"""

import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import pydantic
from core_shared.exceptions import PreconditionFailedError
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.journals import (
    JournalDomainError,
    JournalHasAnchoredTasksError,
    JournalNotFoundError,
    RouteValidationError,
)
from core_shared.models.tasks import TaskDomainError
from fastapi import HTTPException
from sqlalchemy.exc import DataError

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    DuplicateTagNameError,
    TagNotFoundError,
)
from app.core.integrations.immich.conflict_resolution_service import (
    ImmichConflictContactRequiredError,
    ImmichConflictNotFoundError,
)
from app.infrastructure.database_errors import describe_data_error
from app.mcp.shared.response_builders import MCPErrors, MCPLogger, MCPToolError

# String arguments longer than this are logged by size only: a GPX track can be
# megabytes, and copying it into every log line helps nobody.
_MAX_LOGGED_STRING_LENGTH = 1000

P = ParamSpec("P")
R = TypeVar("R")


def mcp_unified_error_handler(
    operation_name: str,
    operation_type: str = "general",  # "contact", "search", "management", "general"
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
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

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                # Log operation start with appropriate context
                from pydantic import BaseModel

                # Make kwargs serializable for structlog JSONRenderer
                serializable_kwargs: dict[str, Any] = {}
                for k, v in kwargs.items():
                    if isinstance(v, BaseModel):
                        serializable_kwargs[k] = v.model_dump()
                    elif isinstance(v, str) and len(v) > _MAX_LOGGED_STRING_LENGTH:
                        serializable_kwargs[k] = f"<str: {len(v)} chars>"
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

            except MCPToolError:
                # The tool's own refusal, already in the shape a client reads.
                # First, so the catch-all below cannot flatten it into
                # "Internal error".
                raise

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
                raise MCPErrors.error(
                    error_type="Conflict",
                    message=e.message,
                    context={
                        "code": "PRECONDITION_FAILED",
                        "resource_type": e.resource_type,
                        "resource_id": str(e.resource_id),
                        "current_version": e.current_etag,
                    },
                ) from e

            except ContactNotFoundError as e:
                MCPLogger.log_not_found_error(operation_name, "Contact", str(e))
                raise MCPErrors.not_found("Contact", str(e)) from e

            except ContactValidationError as e:
                MCPLogger.log_validation_error(operation_name, str(e))
                raise MCPErrors.validation(e.field, e.message) from e

            except TagNotFoundError as e:
                # Without this, a missing tag is indistinguishable from a server
                # failure, which callers cannot act on. Mirrors the journal
                # domain handling below. The builder formats the second argument
                # as the id, so pass the id itself rather than the message.
                MCPLogger.log_not_found_error(operation_name, "Tag", e.tag_id)
                raise MCPErrors.not_found("Tag", e.tag_id) from e

            except DuplicateTagNameError as e:
                MCPLogger.log_validation_error(operation_name, str(e))
                raise MCPErrors.validation("name", str(e)) from e

            except ImmichConflictNotFoundError as e:
                # A DomainError rather than a ValueError, so without this it
                # would fall through to the catch-all as an internal error.
                MCPLogger.log_not_found_error(
                    operation_name, "Conflict", str(e.conflict_id)
                )
                raise MCPErrors.not_found("Conflict", e.conflict_id) from e

            except ImmichConflictContactRequiredError as e:
                MCPLogger.log_validation_error(operation_name, e.message)
                raise MCPErrors.validation("contact_id", e.message) from e

            except JournalNotFoundError as e:
                MCPLogger.log_not_found_error(operation_name, "Journal", str(e))
                raise MCPErrors.not_found("Journal", str(e)) from e

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
                raise MCPErrors.error(
                    error_type="Journal has anchored tasks",
                    message=e.message,
                    context={"code": "JOURNAL_HAS_ANCHORED_TASKS", **e.error_meta()},
                ) from e

            except RouteValidationError as e:
                # Above the journal catch-all, which would bury the field in
                # prose: a caller sending a bad GPX track needs to be told the
                # refusal is about ``gpx_data``, as the REST surface does.
                MCPLogger.log_validation_error(operation_name, e.message)
                raise MCPErrors.validation(e.field, e.reason) from e

            except JournalDomainError as e:
                # Handles all journal domain errors including validation errors raised
                # by dataclasses.replace() __post_init__ and UUID parsing errors.
                MCPLogger.log_validation_error(operation_name, e.message)
                if e.status_code == 404:
                    raise MCPErrors.error(
                        error_type="Not found",
                        message=e.message,
                    ) from e
                raise MCPErrors.error(
                    error_type="Journal error",
                    message=e.message,
                ) from e

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
                    raise MCPErrors.error(
                        error_type="Not found",
                        message=e.message,
                    ) from e
                raise MCPErrors.error(
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
                ) from e

            except json.JSONDecodeError as e:
                MCPLogger.log_validation_error(
                    operation_name, f"Invalid JSON: {str(e)}"
                )
                field_name = (
                    "contact_data" if operation_type == "management" else "JSON"
                )
                raise MCPErrors.validation(
                    field_name, f"Failed to parse JSON data: {str(e)}"
                ) from e

            except pydantic.ValidationError as e:
                MCPLogger.log_validation_error(
                    operation_name, f"Schema validation failed: {str(e)}"
                )
                # Every rejection, not just the first: a call that got three
                # fields wrong should not need three round trips to find out.
                errors = e.errors()
                if not errors:
                    raise MCPErrors.validation("Input", str(e)) from e

                def _path(error: Any) -> str:
                    return (
                        ".".join(str(part) for part in error.get("loc", ())) or "Input"
                    )

                field_name = _path(errors[0])
                message = "; ".join(
                    f"{_path(error)}: {error['msg']}" for error in errors
                )
                raise MCPErrors.validation(field_name, message) from e

            except ValueError as e:
                MCPLogger.log_validation_error(operation_name, str(e))
                raise MCPErrors.validation("Input", str(e)) from e

            except HTTPException as e:
                # A service has no business raising an HTTP error, but one that
                # slips through must not be flattened: HTTPException is neither
                # a domain error nor a ValueError, so the catch-all below used
                # to report it as "Internal error" and lose the detail that
                # said what was actually wrong.
                MCPLogger.log_validation_error(operation_name, str(e.detail))
                raise MCPErrors.error(
                    error_type="Validation error",
                    message=str(e.detail),
                    context={"status_code": e.status_code},
                ) from e

            except DataError as e:
                # The database refusing a value for its column — too long, out
                # of range, wrong type — is a bad request, not a server fault,
                # and the driver's message names the constraint. Reporting it
                # as an internal error tells an agent nothing it can act on.
                # describe_data_error redacts the literal Postgres quotes into
                # that message, so the caller's own data is not read back to it.
                MCPLogger.log_validation_error(operation_name, str(e))
                raise MCPErrors.validation(
                    "type_data" if operation_type == "journal" else "Input",
                    describe_data_error(e),
                ) from e

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
                    raise MCPErrors.error(
                        error_type="Search error",
                        message=f"An error occurred while {operation_name}",
                        context=search_context,
                    ) from e
                else:
                    # Handle general errors
                    MCPLogger.log_operation_error(operation_name, str(e))
                    context = (
                        {"operation_type": operation_type}
                        if operation_type != "general"
                        else None
                    )
                    raise MCPErrors.internal(operation_name, context=context) from e

        return wrapper

    return decorator
