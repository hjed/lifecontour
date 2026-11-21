"""Why a task lapsed, and the rule that decides it.

A task is **lapsed** when the user has let a commitment slide: it is still not
done, and either the journal it was due in has passed or that journal has been
cancelled. Lapsed tasks leave the dashboard silently and stay visible on their
journals, marked, where the user can resurrect, cancel or complete them.

**Lapsed is derived on every read and never stored.** There is no column, no
flag and no background job that sets one. A stored flag would need something to
notice midnight passing in each user's timezone, and would be wrong between that
moment and whenever the job next ran — for a property that costs one date
comparison to compute correctly.

The rule is pure, and takes dates rather than journals or a timezone, for the
reason the date resolver splits the same way: a caller deriving this for many
tasks resolves the user's timezone **once** and hands the resolved dates in. See
``app.core.journal.services.journal_date_resolver`` for where those dates come
from.

The **reason** is returned rather than a boolean because the two causes are not
the same news. "The day went by" and "the meeting was cancelled" ask the user
for different things, so a surface words them differently rather than showing
one marker for both. A caller that only wants the boolean asks whether the
reason is ``None``.

**Only a journal-only task lapses.** Spec invariant 7: a task on a list never
lapses. When its date passes it becomes *overdue* and stays on its list instead
of going quiet. :func:`task_lapse_reason` is the gate that decides whether the
rule applies to a task at all; :func:`derive_lapse_reason` is the rule itself,
for a task it does apply to.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from .task_status import TaskStatus

if TYPE_CHECKING:
    import datetime

    from .entities import Task
    from .read_model import TaskJournalRef


class LapseReason(StrEnum):
    """Why a task is lapsed.

    Values:
        DATE_PASSED: The due journal's date is behind today in the user's
            timezone. The ordinary lapse.
        DUE_JOURNAL_CANCELLED: The due journal is a cancelled event. The moment
            the commitment was pinned to is not going to happen, whatever its
            date says.
    """

    DATE_PASSED = "date_passed"
    DUE_JOURNAL_CANCELLED = "due_journal_cancelled"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


def derive_lapse_reason(
    *,
    status: TaskStatus,
    due_journal_date: datetime.date,
    due_journal_cancelled: bool,
    today: datetime.date,
) -> LapseReason | None:
    """Why this task is lapsed, or ``None`` if it is not.

    Both dates must already be resolved in the acting user's timezone — the
    function has no way to check that, and a UTC-anchored ``today`` would give
    the wrong answer for most of the world for part of every day.

    Args:
        status: The task's current status
        due_journal_date: The due journal's date, in the user's timezone
        due_journal_cancelled: Whether the due journal is a cancelled event
        today: Today's date, in the user's timezone

    Returns:
        The reason, or ``None`` when the task is not lapsed.
    """
    # A commitment that has been met or called off cannot then be let slide.
    # Checked before either cause rather than folded into them, because "done
    # and cancelled tasks are never lapsed" is a rule about the task, not a
    # qualification on the two rules about its journal.
    if status is not TaskStatus.NOT_DONE:
        return None

    # Cancellation is reported ahead of a passed date when both hold. It is the
    # more specific and more actionable of the two, and it carries no date
    # condition of its own: a cancelled journal still in the future lapses its
    # task, because the moment it named is not going to happen.
    if due_journal_cancelled:
        return LapseReason.DUE_JOURNAL_CANCELLED

    # Strictly before today, mirroring ``is_future_dated``'s strictly after.
    # Today is neither future nor passed, so a task due today is outstanding
    # rather than lapsed — and the read-time rule agrees with the write-time
    # invariant about the same journal, which an inclusive boundary here would
    # break the moment a task was created for a journal earlier the same day.
    if due_journal_date < today:
        return LapseReason.DATE_PASSED

    return None


def task_lapse_reason(
    *,
    task: Task,
    due_journal: TaskJournalRef | None,
    today: datetime.date,
) -> LapseReason | None:
    """Why this task is lapsed, or ``None`` if it is not or cannot lapse.

    The one place that decides which tasks the lapse rule applies to:

    - **A task on a list never lapses** (spec invariant 7). A late list task is
      overdue and stays on its list; reporting it as lapsed would hide it the
      way a journal-only task is hidden.
    - **A task with no due journal has nothing to lapse against.** Only a list
      task can have none, so this is the same answer reached a second way, and
      it is what lets the type of ``due_journal`` be optional.

    Every other task is journal-only, and gets :func:`derive_lapse_reason`'s
    answer unchanged.

    Args:
        task: The task being read
        due_journal: Its due journal, already resolved in the user's timezone,
            or ``None`` when it has none
        today: Today's date, in the user's timezone

    Returns:
        The reason, or ``None`` when the task is not lapsed.
    """
    if task.task_list_id is not None or due_journal is None:
        return None
    return derive_lapse_reason(
        status=task.status,
        due_journal_date=due_journal.date,
        due_journal_cancelled=due_journal.cancelled,
        today=today,
    )
