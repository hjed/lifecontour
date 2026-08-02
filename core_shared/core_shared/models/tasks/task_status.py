"""Status enumeration for tasks.

A task has exactly one of three statuses. There is deliberately no in-progress,
blocked, or deferred state: deferring a task is expressed by retargeting it onto
a later journal, not by a status.

The values are the strings stored in ``tasks.status`` and accepted by the
``ck_tasks_status`` CHECK constraint.
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    """Status of a task.

    Values:
        NOT_DONE: The default on creation; the commitment is outstanding.
        DONE: The commitment was met. Reversible back to NOT_DONE.
        CANCELLED: The commitment is no longer relevant. A soft terminal state,
            reopened only by retargeting the task onto a new future journal.
    """

    NOT_DONE = "not_done"
    DONE = "done"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
