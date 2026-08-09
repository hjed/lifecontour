"""Task domain models."""

from .entities import Task
from .exceptions import (
    TaskAnchorJournalNotFoundError,
    TaskDomainError,
    TaskDueJournalNotFutureError,
    TaskJournalAnchor,
    TaskJournalIsAnchorError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatusTransitionError,
    TaskValidationError,
)
from .lapse import LapseReason, derive_lapse_reason
from .read_model import (
    TaskContactRef,
    TaskJournalRef,
    TaskReadModel,
    build_task_read_model,
)
from .task_status import TaskStatus, is_status_transition_allowed

__all__ = [
    "LapseReason",
    "Task",
    "TaskAnchorJournalNotFoundError",
    "TaskContactRef",
    "TaskDomainError",
    "TaskDueJournalNotFutureError",
    "TaskJournalAnchor",
    "TaskJournalIsAnchorError",
    "TaskJournalRef",
    "TaskNotFoundError",
    "TaskReadModel",
    "TaskReopenNotAcknowledgedError",
    "TaskStatus",
    "TaskStatusTransitionError",
    "TaskValidationError",
    "build_task_read_model",
    "derive_lapse_reason",
    "is_status_transition_allowed",
]
