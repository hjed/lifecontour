"""Unit tests for how the shared MCP error handler renders task domain errors.

Without a branch of its own, every task rejection falls to the decorator's
catch-all and comes back as *"An error occurred while create_task"* — which
tells an AI client nothing it can act on, and would quietly break the phase's
requirement that both surfaces reject with a message naming the constraint.

The tasks domain's errors are worth stating individually because each one is
actionable in a different way: a 404 anchor means *pick another journal*, a
non-future due journal means *pick a later one*, and an empty text means *say
what the commitment is*.
"""

import json
from datetime import date

from core_shared.exceptions import DomainError
from core_shared.models.tasks import (
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskStatus,
    TaskStatusTransitionError,
    TaskValidationError,
)

from app.mcp.shared.decorators import mcp_unified_error_handler


async def _render(error: Exception) -> dict[str, str]:
    @mcp_unified_error_handler("create_task", "task")
    async def failing() -> str:
        raise error

    rendered: dict[str, str] = json.loads(await failing())
    return rendered


class TestTaskErrorsReachTheClient:
    """Each rejection keeps the message the domain wrote for it."""

    async def test_an_unreachable_anchor_is_reported_as_not_found(self) -> None:
        response = await _render(TaskAnchorJournalNotFoundError("due", 42))

        assert response["error"] == "Not found"
        assert "due journal (ID 42)" in response["message"]

    async def test_the_anchor_message_still_names_the_constraint(self) -> None:
        """A model that is told only "not found" will retry the same journal."""
        response = await _render(TaskAnchorJournalNotFoundError("creating", 7))

        assert "exist and belong to you" in response["message"]

    async def test_a_non_future_due_journal_carries_both_dates(self) -> None:
        response = await _render(
            TaskDueJournalNotFutureError(9, date(2026, 8, 1), date(2026, 8, 6))
        )

        assert response["error"] == "Task error"
        assert "2026-08-01" in response["message"]
        assert "2026-08-06" in response["message"]

    async def test_a_validation_failure_names_the_field(self) -> None:
        response = await _render(TaskValidationError("text", "Task text is required"))

        assert "text" in response["message"]
        assert "Task text is required" in response["message"]

    async def test_a_missing_task_is_reported_as_not_found(self) -> None:
        response = await _render(TaskNotFoundError(5))

        assert response["error"] == "Not found"
        assert "5" in response["message"]

    async def test_a_refused_transition_is_actionable_rather_than_not_found(
        self,
    ) -> None:
        """A cancelled task exists; what is refused is the move, not the lookup.

        Rendering this as "Not found" would send a model looking for a task it
        can already see.
        """
        response = await _render(
            TaskStatusTransitionError(TaskStatus.CANCELLED, TaskStatus.NOT_DONE)
        )

        assert response["error"] == "Task error"
        assert "cancelled" in response["message"]

    async def test_a_refused_transition_names_the_way_out(self) -> None:
        """Retargeting is the operation the model should reach for instead."""
        response = await _render(
            TaskStatusTransitionError(TaskStatus.CANCELLED, TaskStatus.DONE)
        )

        assert "retarget" in response["message"].lower()


class TestTheBranchIsNotTooBroad:
    """Only the tasks domain gets this treatment."""

    async def test_an_unrelated_domain_error_still_falls_through(self) -> None:
        """A bare ``DomainError`` is not a task error and must not borrow its shape."""
        response = await _render(DomainError("something else went wrong", 400))

        assert response["error"] == "Internal error"

    async def test_an_unexpected_failure_is_still_an_internal_error(self) -> None:
        """A genuine bug must not be dressed up as an actionable rejection."""
        response = await _render(RuntimeError("boom"))

        assert response["error"] == "Internal error"
