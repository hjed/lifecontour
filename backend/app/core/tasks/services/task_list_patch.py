"""A partial update of a task list's own fields: its name and its icon.

See :mod:`app.shared.patch` for why a caller names its changes instead of
handing over a whole list built from a read of its own. ``icon=None`` clears
the icon; leaving ``icon`` as ``UNSET`` keeps it.
"""

from dataclasses import dataclass

from core_shared.models.tasks import TaskIcon

from app.shared.patch import UNSET, FieldPatch, Unset


@dataclass(frozen=True, kw_only=True)
class TaskListPatch(FieldPatch):
    """The list fields a caller changes.

    Position and archive state are deliberately absent: a reorder and an
    archive are their own operations with their own rules, not field edits.
    """

    name: str | Unset = UNSET
    icon: TaskIcon | None | Unset = UNSET
