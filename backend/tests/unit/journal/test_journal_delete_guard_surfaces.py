"""Unit tests for how the delete refusal reaches REST and MCP callers.

Phase 1 made ``JournalService.delete_journal`` refuse with an explanatory
message. A message is not enough for the surfaces: the specification asks that
the same failure "identifies the blocking tasks and the journals that surface
them, so an agent can resolve them without going through the UI", and English
prose is not something a caller can build a link from without parsing it.

So this phase adds the *payload* — the same blockers as machine-readable data,
alongside the prose rather than instead of it. Three things are tested here:

- **the payload** — one blocker's wire shape, built by a single function so the
  two surfaces cannot describe the same failure differently;
- **the REST mapping** — that it lands on the JSON:API error object's ``meta``,
  and that every *other* domain error's response is unchanged;
- **the MCP mapping** — that the tool decorator carries the same list and the
  same code, and that it does not swallow the journal domain's other errors on
  the way.

The last test of the parity pair is the point of the phase: one error instance
serialised through both surfaces must produce the *same* blocker list.
"""

import json
from typing import Any

import pytest
from core_shared.models.journals import (
    BlockingTask,
    JournalHasAnchoredTasksError,
    JournalNotFoundError,
    JournalValidationError,
    blocking_task_payload,
)
from core_shared.models.tasks import TaskStatus

from app.api.error_handlers import create_domain_error_response
from app.mcp.shared.decorators import mcp_unified_error_handler

DELETED = 10
OTHER = 20

BLOCKING_TASKS_CODE = "JOURNAL_HAS_ANCHORED_TASKS"


def make_blocking_task(
    *,
    task_id: int = 1,
    text: str = "print the permit",
    status: TaskStatus = TaskStatus.NOT_DONE,
    roles: tuple[str, ...] = ("due",),
    action_journal_id: int = OTHER,
    action_journal_title: str = "Monday Planning",
) -> BlockingTask:
    return BlockingTask(
        task_id=task_id,
        text=text,
        status=status,
        blocking_roles=roles,  # type: ignore[arg-type]
        action_journal_id=action_journal_id,
        action_journal_title=action_journal_title,
    )


async def call_tool_raising(error: Exception) -> dict[str, Any]:
    """Run a tool that fails with ``error`` through the MCP error decorator."""

    @mcp_unified_error_handler("delete_journal", "journal")
    async def failing_tool() -> str:
        raise error

    payload: dict[str, Any] = json.loads(await failing_tool())
    return payload


class TestBlockingTaskPayload:
    """One blocker's wire shape — the single definition both surfaces use."""

    def test_it_carries_everything_needed_to_explain_and_to_link(self):
        """All six fields, because each one is load-bearing: the id to act on
        the task, the text to recognise it, the status to say whether it is
        still live, the roles to say why it blocks, and the action journal's id
        *and* title to render a link without a second request."""
        payload = blocking_task_payload(make_blocking_task(task_id=7))

        assert payload == {
            "task_id": 7,
            "text": "print the permit",
            "status": "not_done",
            "blocking_roles": ["due"],
            "action_journal_id": OTHER,
            "action_journal_title": "Monday Planning",
        }

    @pytest.mark.parametrize(
        "status", [TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED]
    )
    def test_the_status_is_its_string_value(self, status: TaskStatus):
        """The deletion is refused whatever the status, so all three reach the
        wire — as plain strings rather than as an enum a JSON encoder would have
        to know about."""
        payload = blocking_task_payload(make_blocking_task(status=status))

        assert payload["status"] == status.value
        assert type(payload["status"]) is str

    def test_the_roles_are_an_ordered_list_of_strings(self):
        """A task anchored twice reads the same way every time, and "creating"
        comes first because that is the order the rule builds them in."""
        payload = blocking_task_payload(make_blocking_task(roles=("creating", "due")))

        assert payload["blocking_roles"] == ["creating", "due"]

    def test_it_is_json_serialisable_as_it_stands(self):
        """MCP hands its payload to ``json.dumps`` and REST to ``JSONResponse``.
        Neither will accept a dataclass or an enum the encoder has no rule for,
        so the builder has to finish the job rather than half of it."""
        payload = blocking_task_payload(
            make_blocking_task(status=TaskStatus.CANCELLED, roles=("creating", "due"))
        )

        assert json.loads(json.dumps(payload)) == payload


class TestErrorMeta:
    """What the error offers a surface that wants more than the message."""

    def test_it_names_the_journal_and_every_blocker(self):
        meta = JournalHasAnchoredTasksError(
            DELETED,
            (make_blocking_task(task_id=1), make_blocking_task(task_id=2)),
        ).error_meta()

        assert meta is not None
        assert meta["journal_id"] == DELETED
        assert [task["task_id"] for task in meta["blocking_tasks"]] == [1, 2]

    def test_blocker_order_survives(self):
        """The repository returns blockers in id order and the message lists
        them in that order; a payload that reordered them would put the message
        and the data out of step."""
        blockers = tuple(
            make_blocking_task(task_id=i, text=f"task {i}") for i in (3, 1, 2)
        )

        meta = JournalHasAnchoredTasksError(DELETED, blockers).error_meta()

        assert meta is not None
        assert [task["text"] for task in meta["blocking_tasks"]] == [
            "task 3",
            "task 1",
            "task 2",
        ]

    def test_an_error_with_nothing_to_add_offers_nothing(self):
        """The hook is opt-in. Every other domain error keeps the response it
        has today, which is what stops this phase touching them."""
        assert JournalNotFoundError(DELETED).error_meta() is None


class TestRestMapping:
    """``DELETE /api/journals/{id}`` — the JSON:API error object."""

    def test_the_blockers_land_on_the_error_meta(self):
        response = create_domain_error_response(
            JournalHasAnchoredTasksError(DELETED, (make_blocking_task(task_id=7),))
        )

        error = response.errors[0]
        assert error.meta is not None
        assert error.meta["journal_id"] == DELETED
        assert error.meta["blocking_tasks"] == [
            blocking_task_payload(make_blocking_task(task_id=7))
        ]

    def test_the_prose_is_kept_alongside_the_ids(self):
        """The specification asks for an explanation *and* the specification's
        own consumer — an agent — needs the ids. It is both, not a choice."""
        response = create_domain_error_response(
            JournalHasAnchoredTasksError(DELETED, (make_blocking_task(),))
        )

        error = response.errors[0]
        assert error.status == "409"
        assert error.code == BLOCKING_TASKS_CODE
        assert error.detail is not None
        assert "print the permit" in error.detail
        assert error.meta is not None

    def test_the_body_that_reaches_the_wire_still_contains_the_blockers(self):
        """``exclude_none=True`` is what drops ``meta`` from every other error's
        body, so it is worth pinning that it does not drop a populated one."""
        response = create_domain_error_response(
            JournalHasAnchoredTasksError(DELETED, (make_blocking_task(task_id=7),))
        )

        body = response.model_dump(exclude_none=True)

        assert body["errors"][0]["meta"]["blocking_tasks"][0]["task_id"] == 7

    def test_another_domain_error_gains_no_meta(self):
        """The no-regression guard: one error opted in, and only one."""
        response = create_domain_error_response(JournalNotFoundError(DELETED))

        assert response.errors[0].meta is None
        assert "meta" not in response.model_dump(exclude_none=True)["errors"][0]


class TestMcpMapping:
    """MCP ``delete_journal`` — the same failure, for a caller with no UI."""

    @pytest.mark.asyncio
    async def test_the_refusal_carries_the_code_the_prose_and_the_blockers(self):
        payload = await call_tool_raising(
            JournalHasAnchoredTasksError(DELETED, (make_blocking_task(task_id=7),))
        )

        assert payload["code"] == BLOCKING_TASKS_CODE
        assert "print the permit" in payload["message"]
        assert payload["journal_id"] == DELETED
        # Spelled out rather than compared against the builder, so this test
        # does not use the thing it is checking as its own oracle.
        assert payload["blocking_tasks"] == [
            {
                "task_id": 7,
                "text": "print the permit",
                "status": "not_done",
                "blocking_roles": ["due"],
                "action_journal_id": OTHER,
                "action_journal_title": "Monday Planning",
            }
        ]

    @pytest.mark.asyncio
    async def test_the_journal_domains_other_errors_still_reach_the_catch_all(self):
        """The new branch sits above the ``JournalDomainError`` handler, so it
        has to be narrow enough to let everything else past. Without this the
        branch could be widened by accident and every journal error would start
        claiming to have blocking tasks."""
        payload = await call_tool_raising(JournalValidationError("title", "too long"))

        assert payload["error"] == "Journal error"
        assert "blocking_tasks" not in payload
        assert "code" not in payload

    @pytest.mark.asyncio
    async def test_a_missing_journal_is_still_reported_as_missing(self):
        """``JournalNotFoundError`` is handled above both — the ordering that
        keeps somebody else's journal indistinguishable from one that never
        existed."""
        payload = await call_tool_raising(JournalNotFoundError(DELETED))

        assert payload["error"] == "Journal not found"
        assert "blocking_tasks" not in payload


class TestSurfaceParity:
    """The specification asks for *the same* failure on both surfaces."""

    @pytest.mark.asyncio
    async def test_both_surfaces_describe_the_blockers_identically(self):
        """Two wirings, one builder. If either surface ever grows its own
        serialiser this fails, which is the whole reason the builder exists."""
        error = JournalHasAnchoredTasksError(
            DELETED,
            (
                make_blocking_task(task_id=1, text="print the permit"),
                make_blocking_task(
                    task_id=2,
                    text="book the hut",
                    status=TaskStatus.DONE,
                    roles=("creating", "due"),
                    action_journal_id=DELETED,
                    action_journal_title="Permit Meeting",
                ),
            ),
        )

        rest = create_domain_error_response(error).errors[0]
        mcp = await call_tool_raising(error)

        assert rest.meta is not None
        assert rest.meta["blocking_tasks"] == mcp["blocking_tasks"]
        assert rest.meta["journal_id"] == mcp["journal_id"]
        assert rest.detail == mcp["message"]
