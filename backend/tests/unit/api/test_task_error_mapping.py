"""Unit tests for the task domain errors' JSON:API representation.

The specification requires a rejected invariant to return "a clear, actionable
error naming the constraint" on every surface. That obligation starts here: each
task error carries its own machine-readable code and the status its domain
assigned it, so the controller and MCP tool arriving in Phase 5 inherit a correct
payload rather than defining one.
"""

import datetime

import pytest
from core_shared.models.tasks import (
    TaskAnchorJournalNotFoundError,
    TaskDomainError,
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskValidationError,
)

from app.api.error_handlers import create_domain_error_response


@pytest.mark.unit
class TestTaskErrorMapping:
    """Each task invariant failure is distinguishable in the response."""

    def test_anchor_journal_not_found_maps_to_its_own_code(self) -> None:
        """An unreachable anchor is a 404 with a code of its own."""
        response = create_domain_error_response(
            TaskAnchorJournalNotFoundError("due", 22)
        )

        error = response.errors[0]
        assert error.code == "TASK_ANCHOR_JOURNAL_NOT_FOUND"
        assert error.status == "404"
        assert "22" in (error.detail or "")

    def test_due_journal_not_future_maps_to_its_own_code(self) -> None:
        """A past due journal is a 400 — a rejected request, not a missing one."""
        response = create_domain_error_response(
            TaskDueJournalNotFutureError(
                22, datetime.date(2026, 8, 4), datetime.date(2026, 8, 5)
            )
        )

        error = response.errors[0]
        assert error.code == "TASK_DUE_JOURNAL_NOT_FUTURE"
        assert error.status == "400"

    def test_the_two_creation_failures_are_told_apart(self) -> None:
        """Distinct invariants get distinct codes, not one shared task error."""
        anchor = create_domain_error_response(
            TaskAnchorJournalNotFoundError("creating", 11)
        )
        not_future = create_domain_error_response(
            TaskDueJournalNotFutureError(
                22, datetime.date(2026, 8, 4), datetime.date(2026, 8, 5)
            )
        )

        assert anchor.errors[0].code != not_future.errors[0].code

    def test_existing_task_errors_keep_their_codes(self) -> None:
        """The errors Phases 1 and 2 shipped are mapped too, not left generic."""
        assert (
            create_domain_error_response(TaskNotFoundError(7)).errors[0].code
            == "TASK_NOT_FOUND"
        )
        assert (
            create_domain_error_response(TaskValidationError("text", "required"))
            .errors[0]
            .code
            == "TASK_VALIDATION_ERROR"
        )

    def test_an_unmapped_task_error_still_answers_generically(self) -> None:
        """The base class falls back rather than failing to render."""
        response = create_domain_error_response(TaskDomainError("something", 400))

        assert response.errors[0].code == "DOMAIN_ERROR"
