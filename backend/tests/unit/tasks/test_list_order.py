"""Unit tests for the rule that reorders a list's open tasks.

A list's open tasks show in the user's manual order, and the user moves one by
naming the task it should follow — or none, for the top. Naming a neighbour
rather than an index means a client whose view of the list is stale still lands
the task beside the one it was dropped next to.

The rule hands the open tasks' **existing** positions out again in the new
order rather than renumbering from zero, so no position appears that was not
there before: a closed task keeps its slot relative to the open ones, and
reopening it cannot tie with a moved task. It returns only the rows whose
position changes, which is all the repository writes.
"""

import pytest
from core_shared.models.tasks import reorder_open_tasks

pytestmark = pytest.mark.unit

# Ids deliberately out of position order, and positions with gaps starting above
# zero (closed tasks hold 0, 2 and 4), so neither can be mistaken for the other.
_ORDER = ((30, 1), (10, 3), (40, 5), (20, 6))


def _apply(order: tuple[tuple[int, int], ...], moved: dict[int, int]) -> list[int]:
    """The ids in display order after writing ``moved`` over ``order``."""
    positions = dict(order) | moved
    return sorted(positions, key=lambda task_id: (positions[task_id], task_id))


class TestMoves:
    def test_none_moves_a_task_to_the_top(self) -> None:
        moved = reorder_open_tasks(_ORDER, 40, None)

        assert _apply(_ORDER, moved) == [40, 30, 10, 20]

    def test_after_the_last_task_moves_a_task_to_the_bottom(self) -> None:
        moved = reorder_open_tasks(_ORDER, 30, 20)

        assert _apply(_ORDER, moved) == [10, 40, 20, 30]

    def test_a_task_moves_into_the_middle(self) -> None:
        moved = reorder_open_tasks(_ORDER, 20, 30)

        assert _apply(_ORDER, moved) == [30, 20, 10, 40]

    def test_moving_down_one_names_the_next_task(self) -> None:
        moved = reorder_open_tasks(_ORDER, 10, 40)

        assert _apply(_ORDER, moved) == [30, 40, 10, 20]

    def test_moving_up_one_names_the_task_two_above(self) -> None:
        moved = reorder_open_tasks(_ORDER, 40, 30)

        assert _apply(_ORDER, moved) == [30, 40, 10, 20]

    def test_moving_the_second_task_up_one_names_none(self) -> None:
        moved = reorder_open_tasks(_ORDER, 10, None)

        assert _apply(_ORDER, moved) == [10, 30, 40, 20]


class TestNoChange:
    def test_naming_the_current_predecessor_changes_nothing(self) -> None:
        assert reorder_open_tasks(_ORDER, 40, 10) == {}

    def test_none_for_the_top_task_changes_nothing(self) -> None:
        assert reorder_open_tasks(_ORDER, 30, None) == {}

    def test_a_one_task_list_changes_nothing(self) -> None:
        assert reorder_open_tasks(((7, 2),), 7, None) == {}


class TestPositionsAreReused:
    def test_the_moved_positions_are_the_existing_ones_permuted(self) -> None:
        moved = reorder_open_tasks(_ORDER, 20, None)

        final = dict(_ORDER) | moved
        assert sorted(final.values()) == [1, 3, 5, 6]

    def test_only_rows_whose_position_changes_are_returned(self) -> None:
        # Moving 40 to the top shifts 30 and 10 down; 20 keeps position 6.
        moved = reorder_open_tasks(_ORDER, 40, None)

        assert moved == {40: 1, 30: 3, 10: 5}

    def test_duplicate_positions_become_strictly_increasing(self) -> None:
        tied = ((1, 2), (2, 2), (3, 2))

        moved = reorder_open_tasks(tied, 3, None)

        final = dict(tied) | moved
        assert _apply(tied, moved) == [3, 1, 2]
        assert final[3] < final[1] < final[2]


class TestRefusals:
    def test_a_task_cannot_follow_itself(self) -> None:
        with pytest.raises(ValueError, match="itself"):
            reorder_open_tasks(_ORDER, 10, 10)

    def test_a_task_not_in_the_order_is_refused(self) -> None:
        with pytest.raises(ValueError, match="99"):
            reorder_open_tasks(_ORDER, 99, None)

    def test_an_anchor_not_in_the_order_is_refused(self) -> None:
        with pytest.raises(ValueError, match="99"):
            reorder_open_tasks(_ORDER, 10, 99)
