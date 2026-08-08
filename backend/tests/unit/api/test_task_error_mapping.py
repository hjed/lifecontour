"""Unit tests for the task domain errors' JSON:API representation.

The specification requires a rejected invariant to return "a clear, actionable
error naming the constraint" on every surface. That obligation starts here: each
task error carries its own machine-readable code and the status its domain
assigned it, so the controller and MCP tool arriving in Phase 5 inherit a correct
payload rather than defining one.
"""

import datetime

import pytest
from core_shared.models.journals import JournalNotFoundError
from core_shared.models.tasks import (
    TaskAnchorJournalNotFoundError,
    TaskDomainError,
    TaskDueJournalNotFutureError,
    TaskJournalIsAnchorError,
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

    def test_an_anchor_journal_refusal_maps_to_its_own_code(self) -> None:
        """A journal already linked in an anchor role is a 409 of its own.

        Distinguishability is the point rather than tidiness: a surface that can
        tell this apart from a plain not-found can say *"that journal is already
        the due one"*, while one that cannot has only "error" to show. 409
        because the request is well formed and the journal is a real one of the
        caller's — what it conflicts with is the role that journal already holds.
        """
        response = create_domain_error_response(TaskJournalIsAnchorError(7, 22, "due"))

        error = response.errors[0]
        assert error.code == "TASK_JOURNAL_IS_ANCHOR"
        assert error.status == "409"
        assert "22" in (error.detail or "")
        assert "retarget" in (error.detail or "").lower()

    def test_the_anchor_refusal_is_told_apart_from_a_missing_journal(self) -> None:
        """The two rejections attaching can produce must not share a code.

        A journal that is not the user's and one that is already an anchor are
        different problems with different remedies — pick another journal, versus
        it is already linked — and a client can only branch on them if the codes
        differ.
        """
        anchor = create_domain_error_response(TaskJournalIsAnchorError(7, 22, "due"))
        missing = create_domain_error_response(JournalNotFoundError(22))

        assert anchor.errors[0].code != missing.errors[0].code
        assert missing.errors[0].code == "JOURNAL_NOT_FOUND"
        assert missing.errors[0].status == "404"
