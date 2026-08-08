"""The blocked-delete payload has to be discoverable without provoking it.

Phase 5's delete-failure dialog, and any generated client, learn the shape of
this refusal from two documents: the OpenAPI schema for the REST route, and the
MCP tool's description. Both are the *only* place that information lives — the
repo deliberately keeps per-tool MCP documentation in the docstring rather than
in ``mcp-setup.md`` — so both are asserted here.

Without these tests either could be deleted and every other test in the phase
would still pass, which would leave the contract published nowhere.
"""

from typing import Any

import pytest
from core_shared.models.journals import BlockingTask, JournalHasAnchoredTasksError
from core_shared.models.tasks import TaskStatus
from fastmcp import Client, FastMCP

from app.api.journals.schemas import JournalHasAnchoredTasksErrorResponse
from app.main import create_app
from app.mcp.domains.journals.tools import register_journal_tools


@pytest.fixture(scope="module")
def delete_journal_responses() -> dict[str, Any]:
    """The documented responses of ``DELETE /api/journals/{journal_id}``."""
    schema = create_app().openapi()
    responses: dict[str, Any] = schema["paths"]["/api/journals/{journal_id}"]["delete"][
        "responses"
    ]
    return responses


@pytest.fixture
async def delete_journal_tool_description() -> str:
    """The ``delete_journal`` tool's description, as a client receives it."""
    mcp: FastMCP[None] = FastMCP(name="Test")
    register_journal_tools(mcp)

    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert "delete_journal" in tools, "the tool must be registered to be reachable"
    return tools["delete_journal"].description or ""


class TestTheRestRouteDocumentsItsRefusal:
    """A caller should not have to break a journal to learn what breaks."""

    def test_the_conflict_is_declared(
        self, delete_journal_responses: dict[str, Any]
    ) -> None:
        assert "409" in delete_journal_responses

    def test_the_conflict_carries_a_schema_not_only_prose(
        self, delete_journal_responses: dict[str, Any]
    ) -> None:
        """An English description tells a human what happened; a schema is what
        a generated client and the frontend's types are built from."""
        content = delete_journal_responses["409"]["content"]

        assert "application/json" in content
        assert "$ref" in content["application/json"]["schema"]

    def test_the_schema_names_the_blockers_and_where_to_action_them(self) -> None:
        """The fields Phase 5 needs, asserted on the model the route publishes."""
        blocker_fields = JournalHasAnchoredTasksErrorResponse.model_json_schema(
            ref_template="#/$defs/{model}"
        )["$defs"]["BlockingTaskAttributes"]["properties"].keys()

        assert set(blocker_fields) == {
            "task_id",
            "text",
            "status",
            "blocking_roles",
            "action_journal_id",
            "action_journal_title",
        }

    def test_the_code_is_a_required_discriminator_not_an_optional_default(
        self,
    ) -> None:
        """A generated client has to be able to branch on ``code``.

        Declaring these as defaulted strings would leave them *optional* and
        unconstrained in the schema — present in the body but absent from
        ``required``, and typed as any string — so a client could not treat
        the code as the discriminator for this response. This endpoint emits
        exactly one value for each, and the schema now says so.
        """
        error_object = JournalHasAnchoredTasksErrorResponse.model_json_schema(
            ref_template="#/$defs/{model}"
        )["$defs"]["JournalHasAnchoredTasksErrorObject"]

        assert {"status", "code"} <= set(error_object["required"])
        assert error_object["properties"]["code"]["const"] == (
            "JOURNAL_HAS_ANCHORED_TASKS"
        )
        assert error_object["properties"]["status"]["const"] == "409"

    def test_the_not_found_answer_is_declared_too(
        self, delete_journal_responses: dict[str, Any]
    ) -> None:
        """Somebody else's journal reads as missing, which is a documented
        answer rather than an accident."""
        assert "404" in delete_journal_responses


class TestTheMcpToolDocumentsItsRefusal:
    """The docstring is the agent's only documentation for this tool."""

    def test_it_names_the_code_a_client_branches_on(
        self, delete_journal_tool_description: str
    ) -> None:
        assert "JOURNAL_HAS_ANCHORED_TASKS" in delete_journal_tool_description

    def test_it_names_every_field_of_the_payload(
        self, delete_journal_tool_description: str
    ) -> None:
        """An agent that cannot see the field names has to discover them by
        provoking the failure and reading what comes back.

        The expected names are taken from a **real error's payload** rather
        than hand-listed here. A hand-written list is only as complete as
        whoever wrote it — this test first shipped with one, and it silently
        omitted ``journal_id``, which the handler had been returning all
        along. Derived from the payload, any field the refusal grows has to be
        documented or this fails.

        Each name is looked for in its **marked-up** form. A bare substring
        search cannot see the very omission that prompted this: ``journal_id``
        is a substring of ``action_journal_id``, so the missing field appeared
        to be documented by the field that had replaced it.
        """
        payload = JournalHasAnchoredTasksError(
            10,
            (
                BlockingTask(
                    task_id=7,
                    text="print the permit",
                    status=TaskStatus.NOT_DONE,
                    blocking_roles=("due",),
                    action_journal_id=20,
                    action_journal_title="Monday Planning",
                ),
            ),
        ).error_meta()

        returned = set(payload) | set(payload["blocking_tasks"][0])
        undocumented = sorted(
            field
            for field in returned
            if f"``{field}``" not in delete_journal_tool_description
        )

        assert not undocumented, (
            f"the tool returns {undocumented} but its only documentation does "
            "not mention them"
        )

    def test_it_says_what_to_do_about_it(
        self, delete_journal_tool_description: str
    ) -> None:
        """Naming the blockage is half the job; the specification wants the
        agent steered toward resolving it, and toward cancelling the journal as
        the alternative to deleting it."""
        description = delete_journal_tool_description.lower()

        assert "retry" in description
        assert "cancel" in description
