"""A page of tasks, with the total the pages are drawn from."""

from dataclasses import dataclass

from .entities import Task
from .read_model import TaskReadModel
from .task_list import TaskList


@dataclass(frozen=True)
class TaskPage:
    """One page of a paged task read.

    Attributes:
        tasks: The tasks on this page, in the read's order.
        total: How many tasks the read matches across every page — reported
            even for a page past the end, so a caller can still say how many
            there are.
    """

    tasks: tuple[Task, ...]
    total: int


@dataclass(frozen=True)
class TaskReadModelPage:
    """One page of assembled task read models, with the total across pages.

    The read-side twin of :class:`TaskPage`: that one carries the repository's
    entities, this one what the read service assembled from them. Kept a
    separate type rather than a generic so the repository port's contract stays
    exactly what it is.

    Attributes:
        models: The read models on this page, in the read's order.
        total: How many tasks the read matches across every page, reported
            even for a page past the end.
    """

    models: tuple[TaskReadModel, ...]
    total: int


@dataclass(frozen=True)
class TaskListTasks:
    """A list with its tasks: its open ones, and a page of its closed ones.

    Attributes:
        task_list: The list, read once for the whole answer.
        open_tasks: Its open tasks in manual order — every one, or a page.
        completed: A page of its done and cancelled tasks, most recently
            closed first, or ``None`` when the caller did not ask for them.
    """

    task_list: TaskList
    open_tasks: TaskReadModelPage
    completed: TaskReadModelPage | None
