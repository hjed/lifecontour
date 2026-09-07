"""Turning the upcoming-window listing into the dashboard's tasks section.

One pure function over one piece of arithmetic. Which tasks are coming up, in
what order, and which of them are dropped were all decided by
``select_upcoming_tasks``, the rule this section **reuses** rather than
reimplements. A second definition of "what is due this week" would be right the
day it was written and wrong the first time the other one changed.

What is left for this module is the projection: the subset of a task read model
a dashboard row draws, plus ``days_away``.

**``days_away`` is counted from the window's first day, and that is the whole
reason it is published.** The window's first day *is* ``meta.anchor.date``, the
day the page labels itself with, so a chip reading ``Today`` and a header
reading the same date cannot disagree. A browser working the number out by
subtracting the due date from its own idea of today would be a day out, near
midnight, for every user whose configured zone is not the browser's — the same
ruling the upcoming-dates row already carries for its own ``days_away``.

**Nothing here re-sorts, re-filters or caps.** A sort would be a copy of a rule
that already has a home; a cap would contradict the criterion that the whole
window travels so the card's show-more costs no second request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.dashboard.models.sections import DashboardTask, TasksSectionData

if TYPE_CHECKING:
    from core_shared.models.date_window import UpcomingWindow
    from core_shared.models.tasks import Task, TaskReadModel, UpcomingTasks


def tasks_section_for(upcoming: UpcomingTasks) -> TasksSectionData:
    """The tasks section's payload, from the listing's own answer.

    Args:
        upcoming: What the read service found — the window and the tasks in it,
            already selected and already ordered.

    Returns:
        The payload the card renders: the same window, and one row per task in
        the order they arrived.

    Raises:
        ValueError: A task in the listing has no id, which the read service
            cannot produce. See :func:`_persisted_task_id`.
    """
    return TasksSectionData(
        window=upcoming.window,
        tasks=tuple(_row(model, upcoming.window) for model in upcoming.tasks),
    )


def _row(model: TaskReadModel, window: UpcomingWindow) -> DashboardTask:
    """One task as a row draws it — a projection, deciding nothing else."""
    return DashboardTask(
        task_id=_persisted_task_id(model.task),
        text=model.task.text,
        due_journal=model.due_journal,
        days_away=(model.due_journal.date - window.first_day).days,
        contacts=model.contacts,
    )


def _persisted_task_id(task: Task) -> int:
    """The task's id, refusing to build a row for one that has none.

    ``task.id or 0`` is worse than it looks here: the card's inline done action
    acts on this id, so a zero would send a ``PATCH`` to a task that does not
    exist. Unreachable through the read service, which only ever assembles what
    a repository handed back, so this fails loudly rather than being papered
    over.

    Deliberately a second copy of ``app.api.tasks.schemas.persisted_task_id``
    rather than an import: this is core code and that is an API module, so
    reaching for it would invert the dependency the layering rests on. Extract
    the pair to the tasks domain at a third caller, not before (delivery
    rule 7 — duplicate and record rather than bloat the phase that noticed).
    """
    if task.id is None:
        raise ValueError(
            "Cannot build a dashboard task row for a task that is not persisted"
        )
    return task.id
