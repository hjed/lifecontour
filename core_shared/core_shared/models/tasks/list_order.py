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
    return _assign_slots(current, ids, reordered)


def arrange_open_tasks(
    order: Sequence[tuple[int, int]],
    task_ids: Sequence[int],
    *,
    after_task_id: int | None = None,
    before_task_id: int | None = None,
) -> dict[int, int]:
    """Move a block of open tasks, in the order given, to one place on the list.

    The named tasks leave their old places and every other open task keeps its
    relative order. The block then lands at the top, directly after
    ``after_task_id``, or directly before ``before_task_id``. Naming every open
    task with no anchor sets the whole order; naming one task with
    ``after_task_id`` is :func:`reorder_open_tasks`'s single move.

    Args:
        order: The list's open tasks as ``(id, position)`` pairs, in display
            order — ``(position, id)`` ascending.
        task_ids: The block, in the order it should take.
        after_task_id: The open task, outside the block, it should follow.
        before_task_id: The open task, outside the block, it should precede.

    Returns:
        The new position of every task whose position changes, keyed by id —
        the existing positions handed out again, as :func:`reorder_open_tasks`
        does. Empty when the tasks are already arranged so.

    Raises:
        ValueError: When the block is empty or repeats a task, a task or anchor
            is not in ``order``, an anchor is in the block, or both anchors are
            given. Callers check all of these first; reaching this is a bug.
    """
    current = dict(order)
    ids = [open_task_id for open_task_id, _ in order]
    block = list(task_ids)
    if not block:
        raise ValueError("an arrangement needs at least one task")
    if after_task_id is not None and before_task_id is not None:
        raise ValueError(
            "an arrangement takes after_task_id or before_task_id, not both"
        )
    seen: set[int] = set()
    for named in block:
        if named in seen:
            raise ValueError(f"task {named} is named twice")
        if named not in current:
            raise ValueError(f"task {named} is not an open task in this order")
        seen.add(named)
    anchor = after_task_id if after_task_id is not None else before_task_id
    if anchor is not None and (anchor in seen or anchor not in current):
        raise ValueError(f"task {anchor} cannot anchor this arrangement")

    rest = [open_task_id for open_task_id in ids if open_task_id not in seen]
    if anchor is None:
        insert_at = 0
    else:
        insert_at = rest.index(anchor) + (1 if after_task_id is not None else 0)
    reordered = rest[:insert_at] + block + rest[insert_at:]
    return _assign_slots(current, ids, reordered)


def _assign_slots(
    current: dict[int, int], ids: list[int], reordered: list[int]
) -> dict[int, int]:
    """Hand the existing positions out again in ``reordered``'s order.

    The positions are the current ones, sorted; only where two share a value is
    each raised to one past the one before, so the new order is total. Returns
    the rows whose position changes, and nothing when the order is unchanged.
    """
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
