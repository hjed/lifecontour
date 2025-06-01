"""Core exception classes for the application."""


class DomainError(Exception):
    """Base exception for all domain errors with HTTP status code support."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)
