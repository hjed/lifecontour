"""A page of tasks, with the total the pages are drawn from."""

from dataclasses import dataclass

from .entities import Task


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
