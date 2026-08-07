"""
Shared exceptions for integration workers and backend.

Contains exception classes that are used across the main application
and integration workers.
"""

from typing import Any


class IntegrationError(Exception):
    """Base exception for integration-related errors."""

    def __init__(self, message: str, integration_source: str | None = None):
        """
        Initialize integration error.

        Args:
            message: Error message
            integration_source: Source integration that caused the error
        """
        super().__init__(message)
        self.integration_source = integration_source


class JobCancelledException(IntegrationError):
    """Exception raised when a job is cancelled by the user."""

    def __init__(
        self,
        job_id: str,
        message: str = "Job cancelled by user",
        integration_source: str | None = None,
    ):
        """
        Initialize job cancelled exception.

        Args:
            job_id: ID of the cancelled job
            message: Error message
            integration_source: Source integration that was cancelled
        """
        super().__init__(message, integration_source)
        self.job_id = job_id


class DomainError(Exception):
    """Base exception for all domain errors with HTTP status code support."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def error_meta(self) -> dict[str, Any] | None:
        """Machine-readable detail to travel with the message, or ``None``.

        Most refusals are fully expressed by their prose: a caller told "journal
        4 not found" has everything it can act on. A few are not — a refusal
        that names *other* rows the caller now has to go and deal with leaves
        them parsing English for ids unless the same facts also arrive as data.

        Overriding this puts that data on both surfaces at once: the REST error
        handler renders it as the JSON:API error object's ``meta``, and the MCP
        tool decorator as the failure payload's context. **Opt-in by design** —
        the default is ``None``, which serialises to nothing, so an error that
        has no structured detail keeps exactly the response it has today.

        Whatever is returned must already be plain JSON types; neither surface
        applies an encoder that knows about enums or dataclasses.
        """
        return None
