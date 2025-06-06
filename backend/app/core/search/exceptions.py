"""Custom exceptions for the search domain."""

from app.core.exceptions import DomainError


class SearchDomainError(DomainError):
    """Base exception for search domain errors."""

    pass


class SearchServiceUnavailableError(SearchDomainError):
    """Search service is temporarily unavailable."""

    def __init__(self, service_name: str = "MeiliSearch", details: str | None = None):
        message = f"Search service ({service_name}) is temporarily unavailable"
        if details:
            message += f": {details}"
        super().__init__(message, 503)
        self.service_name = service_name
        self.details = details


class SearchQueryError(SearchDomainError):
    """Invalid search query provided."""

    def __init__(self, query: str, reason: str):
        super().__init__(f"Invalid search query '{query}': {reason}", 400)
        self.query = query
        self.reason = reason


class SearchIndexError(SearchDomainError):
    """Search index operation failed."""

    def __init__(self, index_name: str, operation: str, details: str | None = None):
        message = (
            f"Search index operation '{operation}' failed for index '{index_name}'"
        )
        if details:
            message += f": {details}"
        super().__init__(message, 500)
        self.index_name = index_name
        self.operation = operation
        self.details = details


class SearchConfigurationError(SearchDomainError):
    """Search service configuration error."""

    def __init__(self, setting: str, details: str | None = None):
        message = f"Search configuration error for setting '{setting}'"
        if details:
            message += f": {details}"
        super().__init__(message, 500)
        self.setting = setting
        self.details = details
