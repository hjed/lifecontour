"""Unit tests for the task status transition matrix.

The rule is pure — it needs no repository, no clock and no user — so it lives on
the domain enum's module and is tested here against all nine cells rather than
being inferred from the service tests that consume it.

Two refusals carry the whole of the specification's lifecycle stance for a
journal-only task: *cancelled* is left only by retargeting the task onto a new
future journal (Phase 7), which always lands on *not done*. Both edges out of
cancelled are therefore closed here, and the error says which way out exists.

A task on a list has no closed cell (ITER21 Phase 24): it is reopened directly.
"""

import pytest
from core_shared.models.tasks import (
    TaskStatus,
    TaskStatusTransitionError,
    is_status_transition_allowed,
)

ALLOWED: list[tuple[TaskStatus, TaskStatus]] = [
    (TaskStatus.NOT_DONE, TaskStatus.NOT_DONE),
    (TaskStatus.NOT_DONE, TaskStatus.DONE),
    (TaskStatus.NOT_DONE, TaskStatus.CANCELLED),
    (TaskStatus.DONE, TaskStatus.NOT_DONE),
    (TaskStatus.DONE, TaskStatus.DONE),
    (TaskStatus.DONE, TaskStatus.CANCELLED),
    (TaskStatus.CANCELLED, TaskStatus.CANCELLED),
]

REFUSED: list[tuple[TaskStatus, TaskStatus]] = [
    (TaskStatus.CANCELLED, TaskStatus.NOT_DONE),
    (TaskStatus.CANCELLED, TaskStatus.DONE),
]


@pytest.mark.unit
class TestStatusTransitionMatrix:
    """All nine cells: seven open, two closed."""

    @pytest.mark.parametrize(("current", "target"), ALLOWED)
    def test_allows(self, current: TaskStatus, target: TaskStatus) -> None:
        """Every transition the specification permits is permitted."""
        assert is_status_transition_allowed(current, target, on_list=False) is True

    @pytest.mark.parametrize(("current", "target"), REFUSED)
    def test_refuses(self, current: TaskStatus, target: TaskStatus) -> None:
        """Neither edge out of cancelled is a status change."""
        assert is_status_transition_allowed(current, target, on_list=False) is False

    def test_covers_every_pair(self) -> None:
        """The two lists together are the whole matrix, so no cell is untested."""
        assert set(ALLOWED) | set(REFUSED) == {
            (current, target) for current in TaskStatus for target in TaskStatus
        }
        assert not set(ALLOWED) & set(REFUSED)

    def test_done_is_reversible(self) -> None:
        """The specification's one explicitly reversible transition."""
        assert is_status_transition_allowed(
            TaskStatus.DONE, TaskStatus.NOT_DONE, on_list=False
        )

    def test_cancelled_is_reachable_from_every_state(self) -> None:
        """Cancelling is always available, whatever the task is doing now."""
        assert all(
            is_status_transition_allowed(current, TaskStatus.CANCELLED, on_list=False)
            for current in TaskStatus
        )


@pytest.mark.unit
class TestListTaskTransitions:
    """A task on a list is reopened directly, so no cell is closed for it.

    The specification makes reopening a list task a plain status change: a done
    or cancelled list task is set back to not done without retargeting, because
    a list task never lapses and has no future-journal rule to revalidate.
    Cancelled → done is open too (user decision in the Phase 24 plan review),
    so the whole matrix is open on a list.
    """

    @pytest.mark.parametrize(
        ("current", "target"),
        [(current, target) for current in TaskStatus for target in TaskStatus],
    )
    def test_allows_every_pair(self, current: TaskStatus, target: TaskStatus) -> None:
        """Including both edges out of cancelled."""
        assert is_status_transition_allowed(current, target, on_list=True) is True

    def test_a_cancelled_list_task_reopens_as_not_done(self) -> None:
        """The specification's direct reopen, named on its own."""
        assert is_status_transition_allowed(
            TaskStatus.CANCELLED, TaskStatus.NOT_DONE, on_list=True
        )


@pytest.mark.unit
class TestTaskStatusTransitionError:
    """What a refused transition tells the caller."""

    def test_is_a_conflict(self) -> None:
        """The request is well formed; it disagrees with the task's state."""
        error = TaskStatusTransitionError(TaskStatus.CANCELLED, TaskStatus.NOT_DONE)

        assert error.status_code == 409

    @pytest.mark.parametrize(("current", "target"), REFUSED)
    def test_names_both_statuses(self, current: TaskStatus, target: TaskStatus) -> None:
        """A caller cannot act on "refused" without knowing from what, to what.

        Asserted on the sentence that carries them rather than on the bare
        words: the fixed advice at the end of every message contains *"not
        done"*, so ``"done" in str(error)`` would pass for a message that never
        mentioned the target at all.
        """
        error = TaskStatusTransitionError(current, target)

        assert f"A task that is {current} cannot be moved to {target}." in str(error)

    def test_says_how_to_reopen(self) -> None:
        """The one way out of cancelled is named, so the refusal is actionable."""
        error = TaskStatusTransitionError(TaskStatus.CANCELLED, TaskStatus.NOT_DONE)

        assert "retarget" in str(error).lower()

    def test_carries_both_statuses_programmatically(self) -> None:
        """A surface may want the pair without parsing the message."""
        error = TaskStatusTransitionError(TaskStatus.CANCELLED, TaskStatus.DONE)

        assert error.current_status == TaskStatus.CANCELLED
        assert error.target_status == TaskStatus.DONE
