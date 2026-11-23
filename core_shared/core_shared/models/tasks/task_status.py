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
        CANCELLED: The commitment is no longer relevant. A soft terminal state:
            a journal-only task is reopened only by retargeting it onto a new
            future journal, while a task on a list is reopened directly.
    """

    NOT_DONE = "not_done"
    DONE = "done"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


# The closed cells of the journal-only matrix, stated as the exceptions they
# are: every other pair is allowed, and a task on a list has no closed cell.
# Both edges leaving CANCELLED are shut, because the specification gives a
# journal-only cancelled task exactly one exit — retargeting it onto a new
# future journal, which always lands on NOT_DONE and is a different
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


def is_status_transition_allowed(
    current: TaskStatus, target: TaskStatus, *, on_list: bool
) -> bool:
    """Whether a task in ``current`` may be moved to ``target``.

    **The answer depends on where the task lives**, which is why ``on_list`` is
    required rather than defaulted: a caller that forgot to ask would silently
    get the journal-only answer for a list task, or the reverse.

    - A **journal-only** task may not leave *cancelled* by a status change. Its
      one way back is retargeting onto a new future journal, which revalidates
      the future-dated rule that a status change would skip.
    - A task **on a list** may move between any two statuses. It never lapses
      and has no due journal it must be revived onto, so the specification
      makes reopening it direct: a done or cancelled list task is set back to
      not done without retargeting. Cancelled → done is open too, so a list
      task's status is never refused.

    Args:
        current: The status the task has now
        target: The status the caller is asking for
        on_list: Whether the task is on a list (``task_list_id`` is set)

    Returns:
        True unless the task is journal-only and the transition is one of the
        two that leave CANCELLED.
    """
    if on_list:
        return True
    return (current, target) not in _REFUSED_TRANSITIONS
