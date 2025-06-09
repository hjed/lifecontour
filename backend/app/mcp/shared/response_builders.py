"""
MCP response building utilities.

Provides common utilities for building consistent MCP tool responses,
reducing duplication and ensuring consistent error handling.
"""

import json
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class MCPResponseBuilder:
    """Builder for consistent MCP tool responses."""

    @staticmethod
    def success_response(data: BaseModel) -> str:
        """
        Create a successful MCP response.

        Args:
            data: Pydantic model containing the response data

        Returns:
            JSON string formatted for MCP consumption
        """
        return json.dumps(data.model_dump(), indent=2)

    @staticmethod
    def error_response(
        error_type: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Create an error MCP response.

        Args:
            error_type: Type of error (e.g., "Contact not found")
            message: Human-readable error message
            context: Additional context information

        Returns:
            JSON string formatted for MCP consumption
        """
        error_data = {
            "error": error_type,
            "message": message,
        }

        if context:
            error_data.update(context)

        return json.dumps(error_data, indent=2)

    @staticmethod
    def validation_error_response(field: str, message: str) -> str:
        """
        Create a validation error response.

        Args:
            field: Field that failed validation
            message: Validation error message

        Returns:
            JSON string formatted for MCP consumption
        """
        return MCPResponseBuilder.error_response(
            error_type="Validation error",
            message=f"Validation failed for {field}: {message}",
            context={"field": field},
        )

    @staticmethod
    def not_found_error_response(entity_type: str, entity_id: Any) -> str:
        """
        Create a not found error response.

        Args:
            entity_type: Type of entity (e.g., "Contact")
            entity_id: ID of the entity that was not found

        Returns:
            JSON string formatted for MCP consumption
        """
        return MCPResponseBuilder.error_response(
            error_type=f"{entity_type} not found",
            message=f"No {entity_type.lower()} exists with ID: {entity_id}",
            context={f"{entity_type.lower()}_id": entity_id},
        )

    @staticmethod
    def internal_error_response(
        operation: str, context: dict[str, Any] | None = None
    ) -> str:
        """
        Create an internal error response.

        Args:
            operation: Operation that failed
            context: Additional context information

        Returns:
            JSON string formatted for MCP consumption
        """
        return MCPResponseBuilder.error_response(
            error_type="Internal error",
            message=f"An error occurred while {operation}",
            context=context,
        )


class MCPLogger:
    """Consistent logging for MCP operations."""

    @staticmethod
    def log_operation_start(operation: str, **kwargs: Any) -> None:
        """Log the start of an MCP operation."""
        logger.info(f"MCP: {operation}", **kwargs)

    @staticmethod
    def log_operation_success(operation: str, **kwargs: Any) -> None:
        """Log successful completion of an MCP operation."""
        logger.info(f"MCP: {operation} completed successfully", **kwargs)

    @staticmethod
    def log_operation_error(operation: str, error: str, **kwargs: Any) -> None:
        """Log an error during an MCP operation."""
        logger.error(f"MCP: Error in {operation}", error=error, **kwargs)

    @staticmethod
    def log_validation_error(operation: str, error: str, **kwargs: Any) -> None:
        """Log a validation error during an MCP operation."""
        logger.warning(f"MCP: Validation error in {operation}", error=error, **kwargs)

    @staticmethod
    def log_not_found_error(operation: str, entity_type: str, entity_id: Any) -> None:
        """Log a not found error during an MCP operation."""
        logger.warning(
            f"MCP: {entity_type} not found in {operation}",
            entity_type=entity_type,
            entity_id=entity_id,
        )
