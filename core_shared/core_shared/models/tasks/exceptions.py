"""Exceptions for the tasks domain."""

from core_shared.exceptions import DomainError


class TaskDomainError(DomainError):
    """Base exception for task domain errors."""

    pass


class TaskValidationError(TaskDomainError):
    """Exception raised when task validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        # Store field separately for programmatic access (e.g. in error handlers)
        self.field = field
