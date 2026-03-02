"""
Shared exceptions for integration workers and backend.

Contains exception classes that are used across the main application
and integration workers.
"""


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
