"""Unit tests for the field name travelling with a task validation refusal.

``TaskValidationError`` has always known which field it is about — the
constructor takes one — but until now that name reached a caller only as the
``"{field}: {message}"`` prefix of its prose. A create form that has to put the
refusal against the field that caused it would have to parse English to find
out which one, and would break silently the first time the message was reworded.

So the field travels as data, through ``DomainError.error_meta()`` — the
project's existing opt-in hook, whose one previous user is
``JournalHasAnchoredTasksError``. Three things are tested here:

- **the payload** — one key, whatever the field, and JSON-serialisable as it
  stands;
- **the REST mapping** — that it lands on the JSON:API error object's ``meta``
  while every other task error's body is left byte-for-byte as it was;
- **the MCP mapping** — that an agent gets the same field name a browser does,
  because a refusal an agent is expected to correct is no more parseable from
  prose than one a person is.
"""

import json
from datetime import date
from typing import Any

import pytest
from core_shared.models.tasks import (
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskValidationError,
)

from app.api.error_handlers import create_domain_error_response
from app.mcp.shared.decorators import mcp_unified_error_handler

VALIDATION_CODE = "TASK_VALIDATION_ERROR"


async def call_tool_raising(error: Exception) -> dict[str, Any]:
    """Run a tool that fails with ``error`` through the MCP error decorator."""

    @mcp_unified_error_handler("create_task", "task")
    async def failing_tool() -> str:
        raise error

    payload: dict[str, Any] = json.loads(await failing_tool())
    return payload


class TestErrorMeta:
    """What the error offers a surface that wants more than the message."""

    def test_it_names_the_field_the_refusal_is_about(self):
        meta = TaskValidationError("text", "Task text is required").error_meta()

        assert meta == {"field": "text"}

    @pytest.mark.parametrize("field", ["text", "due_journal_id", "user_id"])
    def test_every_field_the_domain_refuses_on_reaches_the_wire(self, field: str):
        """The domain raises this for the text, for either journal anchor and
        for the user, and a surface mapping refusals onto fields needs the name
        whichever one it was — not only the one this phase's form can reach."""
        meta = TaskValidationError(field, "nope").error_meta()

        assert meta is not None
        assert meta["field"] == field

    def test_the_prose_still_carries_the_field_as_well(self):
        """The data is added beside the message rather than instead of it. A
        caller reading only the message — every one of them before this change
        — sees exactly what it saw before."""
        error = TaskValidationError("text", "Task text is required")

        assert error.message == "text: Task text is required"
        assert error.error_meta() == {"field": "text"}

    def test_it_is_json_serialisable_as_it_stands(self):
        """REST hands this to ``JSONResponse`` and MCP to ``json.dumps``;
        neither applies an encoder that knows about anything but plain types."""
        meta = TaskValidationError("text", "Task text is required").error_meta()

        assert json.loads(json.dumps(meta)) == meta

    def test_a_task_error_with_nothing_to_add_offers_nothing(self):
        """The hook is opt-in and stays that way: the other task errors keep
        the responses they have today, which is what stops this change reaching
        them."""
        assert TaskNotFoundError(7).error_meta() is None


class TestRestMapping:
    """``POST /api/journals/{id}/tasks`` — the JSON:API error object."""

    def test_the_field_lands_on_the_error_meta(self):
        response = create_domain_error_response(
            TaskValidationError("text", "Task text is required")
        )

        error = response.errors[0]
        assert error.code == VALIDATION_CODE
        assert error.status == "400"
        assert error.meta == {"field": "text"}

    def test_the_body_that_reaches_the_wire_still_contains_the_field(self):
        """``exclude_none=True`` is what drops ``meta`` from every other
        error's body, so it is worth pinning that it does not drop a populated
        one."""
        response = create_domain_error_response(
            TaskValidationError("text", "Task text is required")
        )

        body = response.model_dump(exclude_none=True)

        assert body["errors"][0]["meta"] == {"field": "text"}

    def test_the_refusal_that_has_its_own_code_is_untouched(self):
        """A due journal in the past is refused by
        ``TaskDueJournalNotFutureError``, which has a code of its own and needs
        no field name to be mapped onto one. It must not start carrying this
        one."""
        response = create_domain_error_response(
            TaskDueJournalNotFutureError(
                journal_id=4,
                journal_date=date(2026, 1, 1),
                today=date(2026, 6, 1),
            )
        )

        error = response.errors[0]
        assert error.code == "TASK_DUE_JOURNAL_NOT_FUTURE"
        assert "field" not in (error.meta or {})

    def test_another_task_error_gains_no_meta(self):
        """The no-regression guard: one task error opted in, and only one."""
        response = create_domain_error_response(TaskNotFoundError(7))

        assert response.errors[0].meta is None
        assert "meta" not in response.model_dump(exclude_none=True)["errors"][0]


class TestMcpMapping:
    """The same refusal, for a caller with no form to put it on."""

    @pytest.mark.asyncio
    async def test_the_refusal_carries_the_field_beside_the_message(self):
        payload = await call_tool_raising(
            TaskValidationError("text", "Task text is required")
        )

        assert payload["error"] == "Task error"
        assert payload["message"] == "text: Task text is required"
        assert payload["field"] == "text"

    @pytest.mark.asyncio
    async def test_a_task_error_with_no_structured_detail_is_unchanged(self):
        """The forwarding is generic — every task error that opts in is carried
        — so the guard that matters is that the ones which have *not* opted in
        answer exactly what they answered before."""
        payload = await call_tool_raising(
            TaskDueJournalNotFutureError(
                journal_id=4,
                journal_date=date(2026, 1, 1),
                today=date(2026, 6, 1),
            )
        )

        assert payload["error"] == "Task error"
        assert "field" not in payload

    @pytest.mark.asyncio
    async def test_a_missing_task_is_still_reported_as_missing(self):
        """The 404 branch sits above the general one and is not disturbed."""
        payload = await call_tool_raising(TaskNotFoundError(7))

        assert payload["error"] == "Not found"
        assert "field" not in payload


class TestSurfaceParity:
    """Both surfaces name the same field, from the same one definition."""

    @pytest.mark.asyncio
    async def test_rest_and_mcp_report_the_same_field(self):
        error = TaskValidationError("due_journal_id", "A journal anchor is required")

        rest = create_domain_error_response(error).errors[0]
        mcp = await call_tool_raising(error)

        assert rest.meta is not None
        assert rest.meta["field"] == mcp["field"] == "due_journal_id"
