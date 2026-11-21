"""Task domain models."""

from .contact_repointing import TaskContactRepointing
from .entities import Task
from .exceptions import (
    TaskAnchorJournalNotFoundError,
    TaskAnchorMissingError,
    TaskDomainError,
    TaskDueDateInPastError,
    TaskDueJournalNotFutureError,
    TaskJournalAnchor,
    TaskJournalIsAnchorError,
    TaskListArchivedError,
    TaskListChangedConcurrentlyError,
    TaskListNotFoundError,
    TaskListValidationError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatusTransitionError,
    TaskValidationError,
)
from .journal_repointing import TaskJournalRepointing
from .lapse import LapseReason, derive_lapse_reason, task_lapse_reason
from .link_role import (
    JournalTaskGroups,
    TaskLinkRole,
    group_tasks_by_link_role,
)
from .list_dates import (
    DueJournalDays,
    ListTaskDue,
    TaskDateState,
    derive_task_date_state,
    ensure_due_date_allowed,
    is_due_date_allowed,
    is_list_task_overdue,
    list_task_due,
)
from .list_order import reorder_open_tasks
from .read_model import (
    TaskContactRef,
    TaskJournalRef,
    TaskReadModel,
    build_task_read_model,
)
from .task_icon import TaskIcon
from .task_list import MAX_TASK_LIST_NAME_LENGTH, TaskList, TaskListArchiveFilter
from .task_list_order import reorder_task_lists
from .task_page import TaskPage
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
    "DueJournalDays",
    "JournalTaskGroups",
    "LapseReason",
    "ListTaskDue",
    "Task",
    "TaskAnchorJournalNotFoundError",
    "TaskAnchorMissingError",
    "TaskContactRef",
    "TaskContactRepointing",
    "TaskDateState",
    "TaskDomainError",
    "TaskDueDateInPastError",
    "TaskDueJournalNotFutureError",
    "TaskIcon",
    "TaskJournalAnchor",
    "TaskJournalIsAnchorError",
    "TaskJournalRef",
    "TaskJournalRepointing",
    "TaskLinkRole",
    "TaskList",
    "TaskListArchiveFilter",
    "TaskListArchivedError",
    "TaskListChangedConcurrentlyError",
    "TaskListNotFoundError",
    "TaskListValidationError",
    "TaskNotFoundError",
    "TaskPage",
    "TaskReadModel",
    "TaskReopenNotAcknowledgedError",
    "TaskStatus",
    "TaskStatusTransitionError",
    "TaskValidationError",
    "UpcomingTasks",
    "UpcomingWindow",
    "build_task_read_model",
    "derive_lapse_reason",
    "derive_task_date_state",
    "ensure_due_date_allowed",
    "group_tasks_by_link_role",
    "is_due_date_allowed",
    "is_list_task_overdue",
    "is_status_transition_allowed",
    "reorder_open_tasks",
    "list_task_due",
    "reorder_task_lists",
    "select_upcoming_tasks",
    "task_lapse_reason",
    "upcoming_window",
]
