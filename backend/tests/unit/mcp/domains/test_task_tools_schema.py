"""Unit tests for the task MCP tools' schemas.

The schema *is* the tool's contract with an AI client — it is what the model
reads to decide what to send — so it is asserted directly rather than inferred
from the Python signature. Two properties matter beyond documentation.

``now`` must be absent. It is the seam the future-dated invariant is judged
against, and a tool able to set it would make that invariant opt-out for any
caller. So must any bare date: a task is due *in a journal*, and offering a date
would invite the tool to create one implicitly.

The tool's documentation lives here too — in the docstring and the parameter
descriptions the schema carries — and nowhere else, so a test asserts it exists.
"""

from typing import Any

import pytest
from fastmcp import Client, FastMCP

from app.mcp.domains.tasks.tools import register_task_tools


async def _tool_schema(name: str) -> dict[str, Any]:
    """A registered tool as an MCP client actually sees it."""
    mcp: FastMCP[None] = FastMCP(name="Test")
    register_task_tools(mcp)

    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert name in tools, "the tool must be registered to be reachable"
    tool = tools[name]
    return {
        "input_schema": tool.inputSchema,
        "description": tool.description or "",
    }


@pytest.fixture
async def create_task_schema() -> dict[str, Any]:
    """The ``create_task`` tool as an MCP client actually sees it."""
    return await _tool_schema("create_task")


@pytest.fixture
async def set_task_status_schema() -> dict[str, Any]:
    """The ``set_task_status`` tool as an MCP client actually sees it."""
    return await _tool_schema("set_task_status")


class TestCreateTaskToolParameters:
    """What an AI client may send."""

    def test_both_anchors_and_the_text_are_required(
        self, create_task_schema: dict[str, Any]
    ) -> None:
        required = set(create_task_schema["input_schema"]["required"])

        assert required == {"creating_journal_id", "due_journal_id", "text"}

    def test_contacts_are_optional(self, create_task_schema: dict[str, Any]) -> None:
        properties = create_task_schema["input_schema"]["properties"]

        assert "contact_ids" in properties
        assert "contact_ids" not in create_task_schema["input_schema"]["required"]

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, create_task_schema: dict[str, Any]
    ) -> None:
        """The service and connection are resolved, not sent."""
        properties = create_task_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties


class TestTheNowSeamIsNotReachableFromATool:
    """Invariant 4 is not opt-out for an AI client either."""

    def test_the_schema_has_no_now_parameter(
        self, create_task_schema: dict[str, Any]
    ) -> None:
        assert "now" not in create_task_schema["input_schema"]["properties"]

    def test_the_schema_offers_no_bare_date(
        self, create_task_schema: dict[str, Any]
    ) -> None:
        """The only way to say when is to name an existing journal."""
        properties = create_task_schema["input_schema"]["properties"]

        assert not [name for name in properties if "date" in name]


class TestTheToolDocumentsItself:
    """The docstring and schema are the tool's only documentation."""

    def test_the_tool_has_a_description(
        self, create_task_schema: dict[str, Any]
    ) -> None:
        assert len(create_task_schema["description"]) > 0

    def test_the_due_journal_parameter_states_the_constraint(
        self, create_task_schema: dict[str, Any]
    ) -> None:
        """A model that cannot see the rule will keep proposing past journals."""
        description = create_task_schema["input_schema"]["properties"][
            "due_journal_id"
        ]["description"]

        assert "future" in description.lower()


def _enum_values(input_schema: dict[str, Any], parameter: str) -> list[str]:
    """The values a parameter admits, however the generator chose to express them.

    An enum-typed parameter may be inlined or hoisted into ``$defs`` behind a
    ``$ref``; both are the same contract to a model, and the test is about the
    contract rather than the layout.
    """
    schema = input_schema["properties"][parameter]
    ref = schema.get("$ref")
    if ref is not None:
        schema = input_schema["$defs"][ref.rsplit("/", 1)[-1]]
    values: list[str] = schema["enum"]
    return values


class TestSetTaskStatusToolParameters:
    """What an AI client may send to change a status."""

    def test_the_task_and_the_status_are_required(
        self, set_task_status_schema: dict[str, Any]
    ) -> None:
        required = set(set_task_status_schema["input_schema"]["required"])

        assert required == {"task_id", "status"}

    def test_the_status_offers_exactly_the_three_domain_values(
        self, set_task_status_schema: dict[str, Any]
    ) -> None:
        """A model reads the schema, so the vocabulary has to be *in* the schema.

        Typing this parameter as a plain string would leave the model guessing
        at "complete", "closed" or "todo" and learning the answer only from a
        rejection.
        """
        values = _enum_values(set_task_status_schema["input_schema"], "status")

        assert set(values) == {"not_done", "done", "cancelled"}

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, set_task_status_schema: dict[str, Any]
    ) -> None:
        properties = set_task_status_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties

    def test_no_journal_parameter_is_offered(
        self, set_task_status_schema: dict[str, Any]
    ) -> None:
        """Marking a task done or cancelled requires no journal."""
        properties = set_task_status_schema["input_schema"]["properties"]

        assert not [name for name in properties if "journal" in name]


class TestSetTaskStatusDocumentsItself:
    """The one refusal a model needs to be told about before it hits it."""

    def test_the_tool_has_a_description(
        self, set_task_status_schema: dict[str, Any]
    ) -> None:
        assert len(set_task_status_schema["description"]) > 0

    def test_the_description_says_how_a_cancelled_task_is_reopened(
        self, set_task_status_schema: dict[str, Any]
    ) -> None:
        """Otherwise a model retries the refused call rather than retargeting."""
        description = set_task_status_schema["description"].lower()

        assert "cancelled" in description
        assert "retarget" in description
