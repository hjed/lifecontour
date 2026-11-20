"""Where a moved list lands among its owner's lists.

A person reorders the lists they can see — the overview and the sidebar show
only **active** lists — so the index a move carries counts active lists alone.
Archived lists are still part of the stored order, though: unarchiving returns a
list to its old place, so a move must leave each archived list where it was
relative to its neighbours rather than pushing them all to one end.

The rule, over every list in ``(position, id)`` order. The index is first
clamped to the last active place — refused never, so a client whose view is
stale (a list deleted in another tab) still lands sensibly. Then:

- a move to the place the list already has changes **nothing**, not even the
  archived lists around it;
- a move **up** puts the list immediately **above** the active list it lands
  before;
- a move **down** puts it immediately **below** the active list it lands after.

So the moved list is the only one that crosses anything: an archived list
between its old and new neighbours stays on the side it was on.

The caller then renumbers every list densely in the order answered here, which
also heals positions two concurrent creates left tied.
"""

from collections.abc import Sequence

from .task_list import TaskList


def _stored_order_key(task_list: TaskList) -> tuple[int, int]:
    if task_list.id is None or task_list.position is None:
        raise ValueError("Only persisted task lists can be reordered")
    return task_list.position, task_list.id


def reorder_task_lists(
    lists: Sequence[TaskList], moved_id: int, index: int
) -> list[int]:
    """Answer every list's id in its new order after moving one list.

    Args:
        lists: All of one owner's lists, archived ones included, in any order;
            they are read in their stored ``(position, id)`` order.
        moved_id: The list to move. It must be among ``lists`` and active.
        index: Its new place among the active lists, 0 at the top. An index
            past the end moves it to the bottom of the active lists.

    Returns:
        The id of every list in ``lists``, top to bottom.

    Raises:
        ValueError: ``moved_id`` is absent or archived, or ``index`` is
            negative. The service resolves and checks the list first, so these
            are programming errors, not answers to a request.
    """
    if index < 0:
        raise ValueError(f"A move index must be zero or greater, got {index}")

    ordered = sorted(lists, key=_stored_order_key)
    moved = next((each for each in ordered if each.id == moved_id), None)
    if moved is None:
        raise ValueError(f"Task list {moved_id} is not among the lists to reorder")
    if moved.is_archived:
        raise ValueError(f"Task list {moved_id} is archived and cannot be moved")

    current = [each.id for each in ordered if not each.is_archived].index(moved_id)
    others = [each for each in ordered if each.id != moved_id]
    active_slots = [slot for slot, each in enumerate(others) if not each.is_archived]
    target = min(index, len(active_slots))

    if target == current:
        return [each.id for each in ordered if each.id is not None]
    if target < current:
        insert_at = active_slots[target]
    else:
        insert_at = active_slots[target - 1] + 1

    others.insert(insert_at, moved)
    return [each.id for each in others if each.id is not None]
