"""Unit tests for the rule that arranges several of a list's open tasks at once.

An agent names a block of open tasks in the order it wants them. The block
leaves its old places, every other open task keeps its relative order, and the
block lands at the top — or directly after one anchor, or directly before
another. Naming every open task sets the whole order; naming one with an anchor
is the single move the list page makes.

Like the single move, the rule hands the open tasks' **existing** positions out
again rather than renumbering, and returns only the rows whose position
changes.
"""

import pytest
from core_shared.models.tasks import arrange_open_tasks

pytestmark = pytest.mark.unit

# Ids out of position order, positions with gaps (closed tasks hold the rest).
_ORDER = ((30, 1), (10, 3), (40, 5), (20, 6), (50, 8))


def _apply(order: tuple[tuple[int, int], ...], moved: dict[int, int]) -> list[int]:
    """The ids in display order after writing ``moved`` over ``order``."""
    positions = dict(order) | moved
    return sorted(positions, key=lambda task_id: (positions[task_id], task_id))


class TestAtTheTop:
    def test_naming_every_task_sets_the_whole_order(self) -> None:
        moved = arrange_open_tasks(_ORDER, [50, 20, 40, 10, 30])

        assert _apply(_ORDER, moved) == [50, 20, 40, 10, 30]

    def test_one_task_moves_to_the_top(self) -> None:
        moved = arrange_open_tasks(_ORDER, [40])

        assert _apply(_ORDER, moved) == [40, 30, 10, 20, 50]

    def test_a_prefix_goes_first_and_the_rest_keep_their_order(self) -> None:
        moved = arrange_open_tasks(_ORDER, [20, 10])

        assert _apply(_ORDER, moved) == [20, 10, 30, 40, 50]


class TestAfterAnAnchor:
    def test_the_block_lands_directly_after_the_anchor(self) -> None:
        moved = arrange_open_tasks(_ORDER, [50, 30], after_task_id=40)

        assert _apply(_ORDER, moved) == [10, 40, 50, 30, 20]

    def test_after_the_last_task_puts_the_block_at_the_bottom(self) -> None:
        moved = arrange_open_tasks(_ORDER, [10, 30], after_task_id=50)

        assert _apply(_ORDER, moved) == [40, 20, 50, 10, 30]

    def test_one_task_after_an_anchor_is_the_single_move(self) -> None:
        moved = arrange_open_tasks(_ORDER, [20], after_task_id=30)

        assert _apply(_ORDER, moved) == [30, 20, 10, 40, 50]


class TestBeforeAnAnchor:
    def test_the_block_lands_directly_before_the_anchor(self) -> None:
        moved = arrange_open_tasks(_ORDER, [50, 30], before_task_id=40)

        assert _apply(_ORDER, moved) == [10, 50, 30, 40, 20]

    def test_before_the_first_task_puts_the_block_at_the_top(self) -> None:
        moved = arrange_open_tasks(_ORDER, [20], before_task_id=30)

        assert _apply(_ORDER, moved) == [20, 30, 10, 40, 50]

    def test_before_the_anchor_beside_the_blocks_old_place(self) -> None:
        # 40 already sits directly before 20: nothing to write.
        assert arrange_open_tasks(_ORDER, [40], before_task_id=20) == {}


class TestNoChange:
    def test_the_order_already_in_effect_changes_nothing(self) -> None:
        assert arrange_open_tasks(_ORDER, [30, 10]) == {}

    def test_after_the_current_predecessor_changes_nothing(self) -> None:
        assert arrange_open_tasks(_ORDER, [40, 20], after_task_id=10) == {}


class TestPositionsAreReused:
    def test_the_positions_are_the_existing_ones_permuted(self) -> None:
        moved = arrange_open_tasks(_ORDER, [50, 20], after_task_id=30)

        final = dict(_ORDER) | moved
        assert sorted(final.values()) == [1, 3, 5, 6, 8]

    def test_only_rows_whose_position_changes_are_returned(self) -> None:
        # 50 to the top: 30, 10, 40 and 20 each shift down one slot.
        moved = arrange_open_tasks(_ORDER, [50])

        assert moved == {50: 1, 30: 3, 10: 5, 40: 6, 20: 8}

    def test_duplicate_positions_become_strictly_increasing(self) -> None:
        tied = ((1, 2), (2, 2), (3, 2))

        moved = arrange_open_tasks(tied, [3, 2])

        final = dict(tied) | moved
        assert final[3] < final[2] < final[1]


class TestRefusals:
    def test_an_empty_block_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            arrange_open_tasks(_ORDER, [])

    def test_a_duplicate_is_refused(self) -> None:
        with pytest.raises(ValueError, match="10"):
            arrange_open_tasks(_ORDER, [10, 20, 10])

    def test_a_task_not_in_the_order_is_refused(self) -> None:
        with pytest.raises(ValueError, match="99"):
            arrange_open_tasks(_ORDER, [10, 99])

    def test_both_anchors_are_refused(self) -> None:
        with pytest.raises(ValueError, match="both"):
            arrange_open_tasks(_ORDER, [10], after_task_id=30, before_task_id=40)

    @pytest.mark.parametrize("anchor", ["after_task_id", "before_task_id"])
    def test_an_anchor_inside_the_block_is_refused(self, anchor: str) -> None:
        with pytest.raises(ValueError, match="20"):
            arrange_open_tasks(_ORDER, [10, 20], **{anchor: 20})

    @pytest.mark.parametrize("anchor", ["after_task_id", "before_task_id"])
    def test_an_anchor_not_in_the_order_is_refused(self, anchor: str) -> None:
        with pytest.raises(ValueError, match="99"):
            arrange_open_tasks(_ORDER, [10], **{anchor: 99})
