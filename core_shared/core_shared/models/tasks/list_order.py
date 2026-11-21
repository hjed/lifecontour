"""The rule that reorders a task list's open tasks.

A list's open tasks show in the user's manual order, ``(position, id)``. The
user moves one by naming the task it should now follow, or ``None`` for the
top: a drag names the task above the drop point, a keyboard "move down" the
next task and "move up" the task two above. A neighbour rather than an index,
because a client whose view of the list is stale still lands the task beside
the one it chose, where an index would put it somewhere else without error.

Only open tasks take part. Closed tasks keep their positions — they sit in the
list's Completed group, ordered by when they were closed — and so the rule
hands the open tasks' **existing** positions out again in the new order instead
of renumbering from zero. While the open positions are distinct — which joins
under the list's lock keep them — no position appears that was not there
before, so a closed task keeps its slot relative to the open ones and reopening
it cannot tie with a task that was moved.

The rule is pure: the repository reads the open tasks under the list's lock,
asks it which rows change, and writes only those.
"""

from collections.abc import Sequence


def reorder_open_tasks(
    order: Sequence[tuple[int, int]], task_id: int, after_task_id: int | None
) -> dict[int, int]:
    """Move one open task to just after another, or to the top.

    Args:
        order: The list's open tasks as ``(id, position)`` pairs, in display
            order — ``(position, id)`` ascending.
        task_id: The task to move.
        after_task_id: The task it should now follow, or ``None`` to move it to
            the top.

    Returns:
        The new position of every task whose position changes, keyed by id.
        Empty when the task is already where it was asked to go.

        The positions handed out are the existing ones, sorted. Only if two open
        tasks share a position — positions are not unique, so the table permits
        it — is each raised to at most one more than the one before, so the new
        order is total.

    Raises:
        ValueError: When ``task_id`` or ``after_task_id`` is not in ``order``,
            or a task is asked to follow itself. Callers check both are open
            tasks on the list before moving; reaching this is a caller's bug.
    """
    current = dict(order)
    ids = [open_task_id for open_task_id, _ in order]
    if task_id not in current:
        raise ValueError(f"task {task_id} is not an open task in this order")
    if after_task_id == task_id:
        raise ValueError(f"task {task_id} cannot be moved after itself")
    if after_task_id is not None and after_task_id not in current:
        raise ValueError(f"task {after_task_id} is not an open task in this order")

    reordered = [open_task_id for open_task_id in ids if open_task_id != task_id]
    insert_at = 0 if after_task_id is None else reordered.index(after_task_id) + 1
    reordered.insert(insert_at, task_id)
    if reordered == ids:
        return {}

    slots = sorted(current.values())
    for index in range(1, len(slots)):
        slots[index] = max(slots[index], slots[index - 1] + 1)

    return {
        moved_id: slot
        for moved_id, slot in zip(reordered, slots, strict=True)
        if current[moved_id] != slot
    }
