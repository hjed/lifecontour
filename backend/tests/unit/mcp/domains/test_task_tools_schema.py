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


@pytest.fixture
async def update_task_text_schema() -> dict[str, Any]:
    """The ``update_task_text`` tool as an MCP client actually sees it."""
    return await _tool_schema("update_task_text")


@pytest.fixture
async def delete_task_schema() -> dict[str, Any]:
    """The ``delete_task`` tool as an MCP client actually sees it."""
    return await _tool_schema("delete_task")


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


@pytest.fixture
async def link_contact_schema() -> dict[str, Any]:
    """The ``link_task_to_contact`` tool as an MCP client actually sees it."""
    return await _tool_schema("link_task_to_contact")


@pytest.fixture
async def unlink_contact_schema() -> dict[str, Any]:
    """The ``unlink_task_from_contact`` tool as an MCP client actually sees it."""
    return await _tool_schema("unlink_task_from_contact")


class TestContactLinkToolParameters:
    """What an AI client may send to link or unlink a contact."""

    def test_linking_needs_a_task_and_a_contact(
        self, link_contact_schema: dict[str, Any]
    ) -> None:
        required = set(link_contact_schema["input_schema"]["required"])

        assert required == {"task_id", "contact_id"}

    def test_unlinking_needs_a_task_and_a_contact(
        self, unlink_contact_schema: dict[str, Any]
    ) -> None:
        required = set(unlink_contact_schema["input_schema"]["required"])

        assert required == {"task_id", "contact_id"}

    def test_injected_collaborators_are_not_part_of_the_link_contract(
        self, link_contact_schema: dict[str, Any]
    ) -> None:
        properties = link_contact_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties

    def test_injected_collaborators_are_not_part_of_the_unlink_contract(
        self, unlink_contact_schema: dict[str, Any]
    ) -> None:
        properties = unlink_contact_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties


class TestTheLinkCarriesNoRelationshipData:
    """The specification's "plain reference", asserted where a model reads it.

    ``link_journal_to_contact`` takes a relationship type, a status and a role.
    A model that has seen that tool will reach for the same arguments here
    unless the schema says there are none — and the transport refuses what the
    schema does not offer, which is where the guarantee actually lives.
    """

    @pytest.mark.parametrize(
        "unwanted", ["relationship_type", "role", "status", "attendance"]
    )
    def test_the_link_schema_offers_no_relationship_field(
        self, link_contact_schema: dict[str, Any], unwanted: str
    ) -> None:
        assert unwanted not in link_contact_schema["input_schema"]["properties"]

    @pytest.mark.parametrize(
        "unwanted", ["relationship_type", "role", "status", "attendance"]
    )
    def test_the_unlink_schema_offers_no_relationship_field(
        self, unlink_contact_schema: dict[str, Any], unwanted: str
    ) -> None:
        assert unwanted not in unlink_contact_schema["input_schema"]["properties"]

    def test_neither_tool_offers_a_journal(
        self,
        link_contact_schema: dict[str, Any],
        unlink_contact_schema: dict[str, Any],
    ) -> None:
        """A contact link is not a journal link, and needs no journal at all."""
        for schema in (link_contact_schema, unlink_contact_schema):
            properties = schema["input_schema"]["properties"]
            assert not [name for name in properties if "journal" in name]


class TestTheContactLinkToolsDocumentThemselves:
    """The docstring and the schema are these tools' only documentation."""

    def test_the_link_tool_has_a_description(
        self, link_contact_schema: dict[str, Any]
    ) -> None:
        assert len(link_contact_schema["description"]) > 0

    def test_the_unlink_tool_has_a_description(
        self, unlink_contact_schema: dict[str, Any]
    ) -> None:
        assert len(unlink_contact_schema["description"]) > 0

    def test_the_link_description_says_a_repeat_is_harmless(
        self, link_contact_schema: dict[str, Any]
    ) -> None:
        """Otherwise an agent avoids a retry it is free to make, or fears a duplicate."""
        description = link_contact_schema["description"].lower()

        assert "already linked" in description

    def test_the_link_description_says_no_role_is_recorded(
        self, link_contact_schema: dict[str, Any]
    ) -> None:
        """The absent parameters are stated, not merely missing.

        A model that notices ``link_journal_to_contact`` takes a role will
        otherwise assume this tool is the wrong one for what it wants.
        """
        description = link_contact_schema["description"].lower()

        assert "role" in description


class TestUpdateTaskTextToolParameters:
    """What an AI client may send to reword a task."""

    def test_the_task_and_the_text_are_required(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        required = set(update_task_text_schema["input_schema"]["required"])

        assert required == {"task_id", "text"}

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        properties = update_task_text_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties

    def test_no_journal_parameter_is_offered(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        """ "Updating a task never requires a journal" — specification, verbatim.

        A journal parameter here would invite a model to supply one, and the
        only thing the service could do with it is create an intermediate link
        the user never asked for. Intermediate links are explicit only.
        """
        properties = update_task_text_schema["input_schema"]["properties"]

        assert not [name for name in properties if "journal" in name]

    def test_no_status_parameter_is_offered(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        """Two tools, two decisions: rewording is not a way to change a status.

        The combined write exists for the ``PATCH`` body that genuinely carries
        both. A model has a tool per intent, so it never has to reason about
        what leaving a field out will do.
        """
        properties = update_task_text_schema["input_schema"]["properties"]

        assert "status" not in properties

    def test_the_schema_has_no_now_parameter(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        assert "now" not in update_task_text_schema["input_schema"]["properties"]


class TestUpdateTaskTextDocumentsItself:
    """What a model has to know before it calls this rather than after."""

    def test_the_tool_has_a_description(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        assert len(update_task_text_schema["description"]) > 0

    def test_the_description_says_text_is_editable_in_any_status(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        """Otherwise a model will not try to fix a typo on a cancelled task."""
        description = update_task_text_schema["description"].lower()

        assert "any status" in description

    def test_the_text_parameter_says_it_replaces_rather_than_appends(
        self, update_task_text_schema: dict[str, Any]
    ) -> None:
        """A model that assumes otherwise will send a fragment and lose the rest."""
        description = update_task_text_schema["input_schema"]["properties"]["text"][
            "description"
        ].lower()

        assert "replaces" in description


class TestDeleteTaskToolParameters:
    """What an AI client may send to destroy a task."""

    def test_only_the_task_is_required(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        required = set(delete_task_schema["input_schema"]["required"])

        assert required == {"task_id"}

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        properties = delete_task_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties

    def test_no_journal_parameter_is_offered(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        """Deleting a task involves no journal; the links go with the row."""
        properties = delete_task_schema["input_schema"]["properties"]

        assert not [name for name in properties if "journal" in name]


class TestDeleteTaskLeadsWithCancelling:
    """The phase's third criterion, asserted rather than merely written.

    "Both docstrings make cancel the ordinary action and delete the exception."
    For an AI client the docstring is not documentation, it is the only steer it
    gets — a model choosing between two tools reads exactly this text, so a
    description that presented deletion as the neutral way to retire a task
    would make the specification's stance true of the UI and false of the agent.
    """

    def test_the_tool_has_a_description(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        assert len(delete_task_schema["description"]) > 0

    def test_the_description_names_cancelling_as_the_ordinary_action(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        """Asserted on the phrase, not on the word.

        Review caught the looser ``"cancel" in description`` being satisfied by
        the substring inside "cancelled" — so a description reading "deleting is
        tidier than cancelling" would have passed while saying the opposite of
        the criterion.
        """
        description = delete_task_schema["description"].lower()

        assert "prefer cancelling" in description
        assert "cancelling is the ordinary" in description

    def test_the_description_names_the_tool_that_cancels(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        """Naming the alternative in prose is not enough to act on it."""
        description = delete_task_schema["description"]

        assert "set_task_status" in description

    def test_the_description_says_the_deletion_cannot_be_undone(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        """The asymmetry between the two is the whole reason to prefer cancelling."""
        description = delete_task_schema["description"].lower()

        assert "cannot be undone" in description

    def test_the_description_says_what_survives_the_deletion(
        self, delete_task_schema: dict[str, Any]
    ) -> None:
        """A model must not warn a user that their journals are at risk.

        ``untouched`` is asserted alongside the two nouns because those words
        appear in a description that says the opposite just as readily as in one
        that says this.
        """
        description = delete_task_schema["description"].lower()

        assert "untouched" in description
        assert "journals" in description
        assert "contacts" in description
