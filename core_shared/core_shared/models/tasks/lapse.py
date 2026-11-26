"""Why a task lapsed, and the rule that decides it.

A task is **lapsed** when the user has let a commitment slide: it is still not
done, and either the journal it was due in has **ended** — its last day is
behind the user — or that journal has been cancelled. A task due in a journal
that is still under way has not lapsed: a multi-day trip's commitments stay live
until the trip is over, exactly as a list task is only overdue once its journal
has ended. Lapsed tasks leave the dashboard silently and stay visible on their
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
of going quiet. :func:`~.list_dates.derive_task_date_state` is the gate that decides whether
the rule applies to a task at all; :func:`derive_lapse_reason` is the rule
itself, for a task it does apply to.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from .task_status import TaskStatus

if TYPE_CHECKING:
    import datetime


class LapseReason(StrEnum):
    """Why a task is lapsed.

    Values:
        DATE_PASSED: The due journal's last day is behind today in the user's
            timezone: the journal has ended. The ordinary lapse.
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
    due_journal_last_day: datetime.date,
    due_journal_cancelled: bool,
    today: datetime.date,
) -> LapseReason | None:
    """Why this task is lapsed, or ``None`` if it is not.

    Both dates must already be resolved in the acting user's timezone — the
    function has no way to check that, and a UTC-anchored ``today`` would give
    the wrong answer for most of the world for part of every day.

    Args:
        status: The task's current status
        due_journal_last_day: The local date the due journal **ends** on, in
            the user's timezone — its date itself for a single-day journal.
            Named for the day it is so no caller passes the journal's first
            day out of habit: that is the day a task is *due*, not the day it
            becomes late.
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

    # Strictly before today: a journal whose last day is today has not ended,
    # so a task due in it is outstanding rather than lapsed. The write-time
    # invariant (``is_future_dated``) asks about the journal's *first* day, and
    # the two agree: a journal that may become a deadline cannot already have
    # ended.
    if due_journal_last_day < today:
        return LapseReason.DATE_PASSED

    return None
