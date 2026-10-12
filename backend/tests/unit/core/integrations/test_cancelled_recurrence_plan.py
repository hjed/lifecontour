"""Unit tests for the keep-next rule over a cancelled recurrence.

When Google truncates or deletes a recurrence, the upcoming occurrences arrive
as one cancellation each, in whatever order the relay delivers them. The rule
is that the first not-yet-started occurrence of each unbroken run of
cancellations stays (marked cancelled) and the rest go. The property tests
below prove that acting on one cancellation at a time - on the cancelled
instance and its successor only - reaches the same end state as planning the
whole recurrence at once, whatever the arrival order.
"""

from collections.abc import Collection, Iterable
from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest

from app.core.integrations.cancelled_recurrence import (
    CancelledInstanceVerdict,
    RecurrenceInstance,
    affected_by_cancel,
    next_upcoming_after,
    plan_cancelled_recurrence,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
KEEP = CancelledInstanceVerdict.KEEP_AS_NEXT
DELETE = CancelledInstanceVerdict.DELETE


def weekly(
    count: int, *, cancelled: Collection[int] = (), first_offset_days: int = 7
) -> list[RecurrenceInstance]:
    """Weekly instances 1..count, the given ids cancelled."""
    return [
        RecurrenceInstance(
            journal_id=index,
            start=NOW + timedelta(days=first_offset_days + 7 * (index - 1)),
            cancelled=index in cancelled,
        )
        for index in range(1, count + 1)
    ]


class TestPlanCancelledRecurrence:
    def test_a_cancelled_tail_keeps_only_its_first_instance(self) -> None:
        instances = weekly(5, cancelled={3, 4, 5})

        assert plan_cancelled_recurrence(instances, NOW) == {
            3: KEEP,
            4: DELETE,
            5: DELETE,
        }

    def test_a_single_cancelled_instance_is_kept(self) -> None:
        assert plan_cancelled_recurrence(weekly(3, cancelled={2}), NOW) == {2: KEEP}

    def test_a_live_instance_starts_a_new_run(self) -> None:
        instances = weekly(6, cancelled={1, 2, 4, 5, 6})

        assert plan_cancelled_recurrence(instances, NOW) == {
            1: KEEP,
            2: DELETE,
            4: KEEP,
            5: DELETE,
            6: DELETE,
        }

    def test_started_instances_are_neither_kept_nor_deleted(self) -> None:
        """An occurrence under way, or over, is history: it is only marked.

        The next one to start is the one kept, so a cancelled run that began
        in the past keeps its first upcoming member.
        """
        instances = [
            RecurrenceInstance(1, NOW - timedelta(days=7), cancelled=True),
            RecurrenceInstance(2, NOW - timedelta(minutes=30), cancelled=True),
            RecurrenceInstance(3, NOW + timedelta(days=7), cancelled=True),
            RecurrenceInstance(4, NOW + timedelta(days=14), cancelled=True),
        ]

        assert plan_cancelled_recurrence(instances, NOW) == {3: KEEP, 4: DELETE}

    def test_input_order_does_not_matter(self) -> None:
        instances = weekly(4, cancelled={2, 3, 4})

        assert plan_cancelled_recurrence(
            list(reversed(instances)), NOW
        ) == plan_cancelled_recurrence(instances, NOW)

    def test_instances_starting_together_order_by_journal_id(self) -> None:
        start = NOW + timedelta(days=3)
        instances = [
            RecurrenceInstance(9, start, cancelled=True),
            RecurrenceInstance(4, start, cancelled=True),
        ]

        assert plan_cancelled_recurrence(instances, NOW) == {4: KEEP, 9: DELETE}

    def test_nothing_cancelled_plans_nothing(self) -> None:
        assert plan_cancelled_recurrence(weekly(3), NOW) == {}


class TestAffectedByCancel:
    def test_the_instance_and_its_upcoming_successor(self) -> None:
        assert affected_by_cancel(weekly(4), 2, NOW) == (2, 3)

    def test_the_last_instance_has_no_successor(self) -> None:
        assert affected_by_cancel(weekly(3), 3, NOW) == (3,)

    def test_an_unknown_instance_affects_nothing(self) -> None:
        assert affected_by_cancel(weekly(3), 99, NOW) == ()

    def test_a_started_successor_is_skipped_over(self) -> None:
        instances = [
            RecurrenceInstance(1, NOW - timedelta(days=1), cancelled=False),
            RecurrenceInstance(2, NOW - timedelta(hours=1), cancelled=False),
            RecurrenceInstance(3, NOW + timedelta(days=6), cancelled=False),
        ]

        assert affected_by_cancel(instances, 1, NOW) == (1, 3)


class TestNextUpcomingAfter:
    """The occurrence whose verdict changes when one leaves the recurrence."""

    def test_the_first_upcoming_occurrence_after_a_start(self) -> None:
        instances = weekly(4)

        assert next_upcoming_after(instances, instances[1].start, NOW) == 3

    def test_a_start_between_occurrences_finds_the_next(self) -> None:
        instances = weekly(3)

        after = instances[0].start + timedelta(days=1)

        assert next_upcoming_after(instances, after, NOW) == 2

    def test_nothing_after_the_last(self) -> None:
        instances = weekly(2)

        assert next_upcoming_after(instances, instances[1].start, NOW) is None

    def test_started_occurrences_are_skipped(self) -> None:
        instances = [
            RecurrenceInstance(1, NOW - timedelta(hours=2), cancelled=False),
            RecurrenceInstance(2, NOW + timedelta(days=7), cancelled=False),
        ]

        assert next_upcoming_after(instances, NOW - timedelta(days=1), NOW) == 2


def _cancel_one_at_a_time(
    count: int, order: Iterable[int], protected: Collection[int]
) -> set[int]:
    """The surviving ids after delivering each cancellation in turn.

    Each delivery marks one instance cancelled, plans the recurrence as it now
    stands, and acts only on the instance and its successor - which is what
    the processor does per ``journal_event.cancelled``.
    """
    state = {i.journal_id: i for i in weekly(count)}
    for journal_id in order:
        instance = state[journal_id]
        state[journal_id] = RecurrenceInstance(
            instance.journal_id, instance.start, cancelled=True
        )
        instances = list(state.values())
        verdicts = plan_cancelled_recurrence(instances, NOW)
        for affected in affected_by_cancel(instances, journal_id, NOW):
            if verdicts.get(affected) is DELETE and affected not in protected:
                del state[affected]
    return set(state)


def _plan_all_at_once(
    count: int, cancelled: Collection[int], protected: Collection[int]
) -> set[int]:
    instances = weekly(count, cancelled=cancelled)
    verdicts = plan_cancelled_recurrence(instances, NOW)
    return {
        i.journal_id
        for i in instances
        if verdicts.get(i.journal_id) is not DELETE or i.journal_id in protected
    }


class TestArrivalOrderIndependence:
    @pytest.mark.parametrize(
        ("count", "cancelled", "protected"),
        [
            (5, (1, 2, 3, 4, 5), ()),
            (5, (2, 3, 4, 5), ()),
            (6, (1, 2, 4, 5, 6), ()),
            (6, (2, 3, 5, 6), ()),
            (5, (1, 2, 3, 4, 5), (3,)),
            (6, (1, 2, 3, 5, 6), (2, 6)),
            (5, (3,), ()),
        ],
    )
    def test_every_arrival_order_matches_one_full_plan(
        self, count: int, cancelled: tuple[int, ...], protected: tuple[int, ...]
    ) -> None:
        expected = _plan_all_at_once(count, cancelled, protected)

        for order in permutations(cancelled):
            assert _cancel_one_at_a_time(count, order, protected) == expected, order
