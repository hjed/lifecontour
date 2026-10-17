"""
MCP response building utilities.

A tool returns its response model, which fastmcp publishes as the tool's
``outputSchema`` and sends as ``structuredContent``. A tool *refuses* by
raising one of the ``MCPErrors`` factories: the ``MCPToolError`` reaches the
client as an ``isError`` result whose text is a JSON payload — ``error``,
``message`` and whatever context (``code``, ``field``, ``current_version``)
the refusal carries for an agent to act on.
"""

import json
import logging
from typing import Any

import structlog
from fastmcp.exceptions import ToolError

logger = structlog.get_logger()


class MCPToolError(ToolError):
    """A tool refusal, sent to the client as ``isError: true``.

    fastmcp passes a ``ToolError`` through unmasked with ``str(error)`` as the
    result's only text, so the message *is* the JSON payload — the same JSON
    the tools used to return as a success.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        # A refusal is expected traffic, already logged by the error handler;
        # fastmcp would otherwise log every one at ERROR.
        super().__init__(json.dumps(payload, indent=2), log_level=logging.WARNING)
        self.payload = payload


class MCPErrors:
    """Factories for the refusals a tool raises: ``raise MCPErrors.not_found(...)``."""

    @staticmethod
    def error(
        error_type: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> MCPToolError:
        """
        A refusal with a type, a human-readable message and optional context.

        Args:
            error_type: Type of error (e.g., "Contact not found")
            message: Human-readable error message
            context: Additional fields merged into the payload
        """
        payload: dict[str, Any] = {"error": error_type, "message": message}
        if context:
            payload.update(context)
        return MCPToolError(payload)

    @staticmethod
    def validation(field: str, message: str) -> MCPToolError:
        """A refusal of one field's value."""
        return MCPErrors.error(
            error_type="Validation error",
            message=f"Validation failed for {field}: {message}",
            context={"field": field},
        )

    @staticmethod
    def not_found(entity_type: str, entity_id: Any) -> MCPToolError:
        """A refusal because the entity does not exist (for this user)."""
        return MCPErrors.error(
            error_type=f"{entity_type} not found",
            message=f"No {entity_type.lower()} exists with ID: {entity_id}",
            context={f"{entity_type.lower()}_id": entity_id},
        )

    @staticmethod
    def internal(operation: str, context: dict[str, Any] | None = None) -> MCPToolError:
        """A server fault, reported without its detail."""
        return MCPErrors.error(
            error_type="Internal error",
            message=f"An error occurred while {operation}",
            context=context,
        )


class MCPLogger:
    """Consistent logging for MCP operations."""

    @staticmethod
    def log_operation_start(operation: str, **kwargs: Any) -> None:
        """Log the start of an MCP operation."""
        logger.info("MCP: Operation started", operation=operation, **kwargs)

    @staticmethod
    def log_operation_success(operation: str, **kwargs: Any) -> None:
        """Log successful completion of an MCP operation."""
        logger.info("MCP: Operation completed", operation=operation, **kwargs)

    @staticmethod
    def log_operation_error(operation: str, error: str, **kwargs: Any) -> None:
        """Log an error during an MCP operation."""
        logger.error(
            "MCP: Operation error",
            operation=operation,
            error=error,
            exc_info=True,
            **kwargs,
        )

    @staticmethod
    def log_validation_error(operation: str, error: str, **kwargs: Any) -> None:
        """Log a validation error during an MCP operation."""
        logger.warning(
            "MCP: Validation error", operation=operation, error=error, **kwargs
        )

    @staticmethod
    def log_not_found_error(operation: str, entity_type: str, entity_id: Any) -> None:
        """Log a not found error during an MCP operation."""
        logger.warning(
            "MCP: Entity not found",
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
        )
