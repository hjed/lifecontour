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


class TaskNotFoundError(TaskDomainError):
    """Exception raised when a task is not found.

    Every repository read and write is scoped to the acting user, so a task
    belonging to somebody else is indistinguishable from one that never
    existed — which is the point. The message deliberately says nothing about
    ownership.
    """

    def __init__(self, task_id: int):
        super().__init__(f"Task with ID {task_id} not found", 404)
        self.task_id = task_id
