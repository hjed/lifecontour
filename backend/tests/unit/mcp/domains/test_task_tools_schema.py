"""Unit tests for the ``create_task`` MCP tool's schema.

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


@pytest.fixture
async def create_task_schema() -> dict[str, Any]:
    """The ``create_task`` tool as an MCP client actually sees it."""
    mcp: FastMCP[None] = FastMCP(name="Test")
    register_task_tools(mcp)

    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert "create_task" in tools, "the tool must be registered to be reachable"
    tool = tools["create_task"]
    return {
        "input_schema": tool.inputSchema,
        "description": tool.description or "",
    }


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
