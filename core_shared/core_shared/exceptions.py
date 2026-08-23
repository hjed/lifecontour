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


class PreconditionFailedError(DomainError):
    """A write's precondition did not match the version it was written against.

    Raised when an ``If-Match`` header (REST) or an ``expected_version``
    argument (MCP) names a version of a resource that is no longer current —
    somebody else wrote to the row between the caller's read and its write.
    Nothing is written; the caller re-reads and re-applies its change.

    ``412 Precondition Failed`` rather than ``409 Conflict``: the request was
    refused because a precondition it stated was not met, which is what 412
    names. The current tag travels in ``error_meta`` so a client can recover
    without a second round trip to find out what it should have sent.
    """

    def __init__(
        self,
        resource_type: str,
        resource_id: int | str,
        current_etag: str | None,
    ):
        """
        Args:
            resource_type: JSON:API resource type, e.g. ``"journals"``.
            resource_id: The resource whose version moved on.
            current_etag: The resource's tag now, or ``None`` if unknown.
        """
        super().__init__(
            f"{resource_type} {resource_id} has been modified since it was read. "
            "Re-read it and re-apply the change.",
            412,
        )
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.current_etag = current_etag

    def error_meta(self) -> dict[str, Any] | None:
        """The identity of the row and the version the caller should have sent."""
        return {
            "resource_type": self.resource_type,
            "resource_id": str(self.resource_id),
            "current_etag": self.current_etag,
        }
