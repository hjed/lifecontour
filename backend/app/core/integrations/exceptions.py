"""
Integration domain exceptions.

Contains exceptions specific to external service integration operations.
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


class SyncError(IntegrationError):
    """Exception raised when synchronization fails."""

    def __init__(
        self,
        message: str,
        integration_source: str | None = None,
        external_id: str | None = None,
        retry_count: int = 0,
    ):
        """
        Initialize sync error.

        Args:
            message: Error message
            integration_source: Source integration that failed
            external_id: External ID that failed to sync
            retry_count: Number of retries attempted
        """
        super().__init__(message, integration_source)
        self.external_id = external_id
        self.retry_count = retry_count


class ExternalServiceError(IntegrationError):
    """Exception raised when external service API calls fail."""

    def __init__(
        self,
        message: str,
        integration_source: str | None = None,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        """
        Initialize external service error.

        Args:
            message: Error message
            integration_source: Source integration that failed
            status_code: HTTP status code from external service
            response_body: Response body from external service
        """
        super().__init__(message, integration_source)
        self.status_code = status_code
        self.response_body = response_body


class AuthenticationError(IntegrationError):
    """Exception raised when authentication with external service fails."""

    def __init__(
        self,
        message: str,
        integration_source: str | None = None,
        auth_type: str | None = None,
    ):
        """
        Initialize authentication error.

        Args:
            message: Error message
            integration_source: Source integration that failed
            auth_type: Type of authentication that failed (oauth, api_key, etc.)
        """
        super().__init__(message, integration_source)
        self.auth_type = auth_type


class ConflictResolutionError(IntegrationError):
    """Exception raised when conflict resolution fails during sync."""

    def __init__(
        self,
        message: str,
        integration_source: str | None = None,
        internal_id: int | None = None,
        external_id: str | None = None,
    ):
        """
        Initialize conflict resolution error.

        Args:
            message: Error message
            integration_source: Source integration that failed
            internal_id: Internal entity ID involved in conflict
            external_id: External entity ID involved in conflict
        """
        super().__init__(message, integration_source)
        self.internal_id = internal_id
        self.external_id = external_id


class RateLimitError(IntegrationError):
    """Exception raised when external service rate limits are exceeded."""

    def __init__(
        self,
        message: str,
        integration_source: str | None = None,
        retry_after: int | None = None,
    ):
        """
        Initialize rate limit error.

        Args:
            message: Error message
            integration_source: Source integration that hit rate limit
            retry_after: Seconds to wait before retrying
        """
        super().__init__(message, integration_source)
        self.retry_after = retry_after
