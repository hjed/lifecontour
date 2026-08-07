"""Status enumeration for tasks.

A task has exactly one of three statuses. There is deliberately no in-progress,
blocked, or deferred state: deferring a task is expressed by retargeting it onto
a later journal, not by a status.

The values are the strings stored in ``tasks.status`` and accepted by the
``ck_tasks_status`` CHECK constraint.

The **transition rule** lives here too, as a pure predicate. It needs no
repository, no clock and no user, so putting it beside the values keeps the
matrix in one readable place instead of spread through the service that applies
it — and lets both the service and any surface that wants to grey out an action
ask the same question.
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


# The closed cells of the matrix, stated as the exceptions they are: every other
# pair is allowed. Both edges leaving CANCELLED are shut, because the
# specification gives cancelled exactly one exit — retargeting the task onto a
# new future journal, which always lands on NOT_DONE and is a different
# operation with its own rules. A status call that could leave cancelled would
# be a second exit that skips those rules, and CANCELLED → DONE would in
# addition assert that a commitment was met after it was declared irrelevant.
#
# CANCELLED → CANCELLED is *not* here: asking for the status a task already has
# is not a reopening.
_REFUSED_TRANSITIONS: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset(
    {
        (TaskStatus.CANCELLED, TaskStatus.NOT_DONE),
        (TaskStatus.CANCELLED, TaskStatus.DONE),
    }
)


def is_status_transition_allowed(current: TaskStatus, target: TaskStatus) -> bool:
    """Whether a task in ``current`` may be moved to ``target``.

    Args:
        current: The status the task has now
        target: The status the caller is asking for

    Returns:
        True unless the transition is one of the two that leave CANCELLED.
    """
    return (current, target) not in _REFUSED_TRANSITIONS
