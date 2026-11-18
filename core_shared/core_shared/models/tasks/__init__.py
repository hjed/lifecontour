"""Task domain models."""

from .contact_repointing import TaskContactRepointing
from .entities import Task
from .exceptions import (
    TaskAnchorJournalNotFoundError,
    TaskDomainError,
    TaskDueJournalNotFutureError,
    TaskJournalAnchor,
    TaskJournalIsAnchorError,
    TaskListNotFoundError,
    TaskListValidationError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatusTransitionError,
    TaskValidationError,
)
from .journal_repointing import TaskJournalRepointing
from .lapse import LapseReason, derive_lapse_reason
from .link_role import (
    JournalTaskGroups,
    TaskLinkRole,
    group_tasks_by_link_role,
)
from .read_model import (
    TaskContactRef,
    TaskJournalRef,
    TaskReadModel,
    build_task_read_model,
)
from .task_icon import TaskIcon
from .task_list import MAX_TASK_LIST_NAME_LENGTH, TaskList, TaskListArchiveFilter
from .task_status import TaskStatus, is_status_transition_allowed
from .upcoming import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    MAX_UPCOMING_DAYS_AHEAD,
    UpcomingTasks,
    UpcomingWindow,
    select_upcoming_tasks,
    upcoming_window,
)

__all__ = [
    "DEFAULT_UPCOMING_DAYS_AHEAD",
    "MAX_TASK_LIST_NAME_LENGTH",
    "MAX_UPCOMING_DAYS_AHEAD",
    "JournalTaskGroups",
    "LapseReason",
    "Task",
    "TaskAnchorJournalNotFoundError",
    "TaskContactRef",
    "TaskContactRepointing",
    "TaskDomainError",
    "TaskDueJournalNotFutureError",
    "TaskIcon",
    "TaskJournalAnchor",
    "TaskJournalIsAnchorError",
    "TaskJournalRef",
    "TaskJournalRepointing",
    "TaskLinkRole",
    "TaskList",
    "TaskListArchiveFilter",
    "TaskListNotFoundError",
    "TaskListValidationError",
    "TaskNotFoundError",
    "TaskReadModel",
    "TaskReopenNotAcknowledgedError",
    "TaskStatus",
    "TaskStatusTransitionError",
    "TaskValidationError",
    "UpcomingTasks",
    "UpcomingWindow",
    "build_task_read_model",
    "derive_lapse_reason",
    "group_tasks_by_link_role",
    "is_status_transition_allowed",
    "select_upcoming_tasks",
    "upcoming_window",
]
