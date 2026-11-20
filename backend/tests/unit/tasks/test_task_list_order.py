"""The rule for where a moved list lands among the owner's lists.

``reorder_task_lists`` takes every list the owner has — archived ones included —
and answers the new order as ids. The index it is given counts the **active**
lists only, because that is the view a person reorders (the overview and the
sidebar never show archived lists); archived lists keep their place relative to
their neighbours, so unarchiving returns a list near where it was.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.tasks import TaskList, reorder_task_lists

pytestmark = pytest.mark.unit

ARCHIVED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _list(list_id: int, position: int, *, archived: bool = False) -> TaskList:
    return TaskList(
        id=list_id,
        user_id="user-1",
        name=f"List {list_id}",
        position=position,
        archived_at=ARCHIVED_AT if archived else None,
    )


def _active(*ids: int) -> list[TaskList]:
    """Active lists in the given order, at positions 0, 1, 2…"""
    return [_list(list_id, position) for position, list_id in enumerate(ids)]


class TestMovingAmongActiveLists:
    def test_moves_a_list_down(self) -> None:
        assert reorder_task_lists(_active(1, 2, 3, 4), 1, 2) == [2, 3, 1, 4]

    def test_moves_a_list_up(self) -> None:
        assert reorder_task_lists(_active(1, 2, 3, 4), 4, 1) == [1, 4, 2, 3]

    def test_moves_a_list_to_the_top(self) -> None:
        assert reorder_task_lists(_active(1, 2, 3), 3, 0) == [3, 1, 2]

    def test_moves_a_list_to_the_last_index(self) -> None:
        assert reorder_task_lists(_active(1, 2, 3), 1, 2) == [2, 3, 1]

    def test_moving_to_its_own_index_changes_nothing(self) -> None:
        assert reorder_task_lists(_active(1, 2, 3), 2, 1) == [1, 2, 3]

    def test_an_index_past_the_end_moves_it_to_the_bottom(self) -> None:
        """A client with a stale view — a list deleted in another tab — still
        lands somewhere sensible rather than being refused."""
        assert reorder_task_lists(_active(1, 2, 3), 1, 99) == [2, 3, 1]

    def test_the_only_active_list_stays_where_it_is(self) -> None:
        lists = [_list(1, 0, archived=True), _list(2, 1), _list(3, 2, archived=True)]

        assert reorder_task_lists(lists, 2, 0) == [1, 2, 3]
        assert reorder_task_lists(lists, 2, 5) == [1, 2, 3]


class TestTheStoredOrderIsRespected:
    def test_lists_are_read_in_position_order_not_input_order(self) -> None:
        lists = [_list(1, 2), _list(2, 0), _list(3, 1)]

        assert reorder_task_lists(lists, 1, 0) == [1, 2, 3]

    def test_tied_positions_order_by_id(self) -> None:
        """Concurrent creates can share a position; ``(position, id)`` decides."""
        lists = [_list(3, 0), _list(1, 0), _list(2, 0)]

        assert reorder_task_lists(lists, 3, 1) == [1, 3, 2]


class TestArchivedListsKeepTheirPlace:
    # Stored order: A1, X2 (archived), A3, A4, X5 (archived)
    def _lists(self) -> list[TaskList]:
        return [
            _list(1, 0),
            _list(2, 1, archived=True),
            _list(3, 2),
            _list(4, 3),
            _list(5, 4, archived=True),
        ]

    def test_the_index_counts_active_lists_only(self) -> None:
        """Index 1 is the second *active* list (3), not the archived 2."""
        assert reorder_task_lists(self._lists(), 4, 1) == [1, 2, 4, 3, 5]

    def test_moving_to_the_top_goes_before_the_first_active_list(self) -> None:
        assert reorder_task_lists(self._lists(), 4, 0) == [4, 1, 2, 3, 5]

    def test_moving_to_the_bottom_goes_after_the_last_active_list(self) -> None:
        """A trailing archived list stays below everything it was below."""
        assert reorder_task_lists(self._lists(), 1, 2) == [2, 3, 4, 1, 5]
        assert reorder_task_lists(self._lists(), 1, 50) == [2, 3, 4, 1, 5]

    def test_moving_to_its_own_place_leaves_an_archived_neighbour_alone(
        self,
    ) -> None:
        """Inserting "before the active list at the index" would hop the
        archived list below the moved one above it; a move that does not change
        the active order changes nothing at all."""
        lists = [_list(1, 0), _list(2, 1, archived=True), _list(3, 2)]

        assert reorder_task_lists(lists, 1, 0) == [1, 2, 3]
        assert reorder_task_lists(lists, 3, 1) == [1, 2, 3]
        assert reorder_task_lists(lists, 3, 9) == [1, 2, 3]

    def test_moving_down_lands_directly_below_its_new_upper_neighbour(
        self,
    ) -> None:
        """An archived list between the new neighbours stays below the moved
        list's old place, not hopped over."""
        lists = [_list(1, 0), _list(2, 1), _list(3, 2, archived=True), _list(4, 3)]

        assert reorder_task_lists(lists, 1, 1) == [2, 1, 3, 4]

    def test_moving_up_lands_directly_above_its_new_lower_neighbour(
        self,
    ) -> None:
        lists = [_list(1, 0), _list(2, 1, archived=True), _list(3, 2), _list(4, 3)]

        assert reorder_task_lists(lists, 4, 1) == [1, 2, 4, 3]

    def test_a_leading_archived_list_stays_above_a_list_moved_to_the_top(
        self,
    ) -> None:
        lists = [_list(1, 0, archived=True), _list(2, 1), _list(3, 2)]

        assert reorder_task_lists(lists, 3, 0) == [1, 3, 2]


class TestProgrammingErrors:
    """The service resolves and checks the moved list first; these guard it."""

    def test_an_absent_list_is_refused(self) -> None:
        with pytest.raises(ValueError, match="7"):
            reorder_task_lists(_active(1, 2), 7, 0)

    def test_an_archived_list_is_refused(self) -> None:
        lists = [_list(1, 0), _list(2, 1, archived=True)]

        with pytest.raises(ValueError, match="archived"):
            reorder_task_lists(lists, 2, 0)

    def test_a_negative_index_is_refused(self) -> None:
        with pytest.raises(ValueError, match="index"):
            reorder_task_lists(_active(1, 2), 1, -1)
