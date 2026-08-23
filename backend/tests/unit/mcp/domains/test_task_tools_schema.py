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

    An enum-typed parameter may be inlined, hoisted into ``$defs`` behind a
    ``$ref``, or — when it is *optional* — wrapped in an ``anyOf`` beside a null
    branch. All three are the same contract to a model, and the test is about
    the contract rather than the layout.
    """
    schema = input_schema["properties"][parameter]
    for branch in schema.get("anyOf", []):
        if branch.get("type") != "null":
            schema = branch
            break
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
async def retarget_task_schema() -> dict[str, Any]:
    """The ``retarget_task`` tool as an MCP client actually sees it."""
    return await _tool_schema("retarget_task")


class TestRetargetTaskToolParameters:
    """What an AI client may send to move a task onto a new due journal."""

    def test_the_task_and_the_new_due_journal_are_required(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        required = set(retarget_task_schema["input_schema"]["required"])

        assert required == {"task_id", "due_journal_id"}

    def test_the_acknowledgement_is_optional_and_defaults_to_not_given(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """An agent that has not been asked to reopen a done task must not.

        The default is the whole point of the gate: a model reaching for this
        tool to extend a deadline should be stopped and told, rather than
        quietly undoing a completion.
        """
        schema = retarget_task_schema["input_schema"]

        assert "acknowledge_reopen" not in schema["required"]
        assert schema["properties"]["acknowledge_reopen"]["default"] is False

    @pytest.mark.parametrize("parameter", ["task_id", "due_journal_id"])
    def test_every_id_is_bounded_to_what_a_column_can_hold(
        self, retarget_task_schema: dict[str, Any], parameter: str
    ) -> None:
        """Python's ``int`` is unbounded; ``INTEGER`` is not.

        Without the bound, ``2147483648`` reaches asyncpg's parameter binding
        and dies there — a 500 for an id no row could ever have.
        """
        schema = retarget_task_schema["input_schema"]["properties"][parameter]

        assert schema["minimum"] == 1
        assert schema["maximum"] == 2_147_483_647

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        properties = retarget_task_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties


class TestTheRetargetReachesNeitherTheNowSeamNorTheCreatingJournal:
    """Two absences, each enforcing a rule the tool must not be able to break."""

    def test_the_schema_has_no_now_parameter(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """Invariant 4 is revalidated on a retarget, and stays non-optional."""
        assert "now" not in retarget_task_schema["input_schema"]["properties"]

    def test_the_schema_offers_no_creating_journal(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """*"Set once and never changes"*, enforced by there being nothing to send.

        The service has no parameter for it either; this asserts the tool did
        not invent one on the way past.
        """
        properties = retarget_task_schema["input_schema"]["properties"]

        assert "creating_journal_id" not in properties

    def test_the_schema_offers_no_bare_date(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """The new due journal must be a journal that already exists."""
        properties = retarget_task_schema["input_schema"]["properties"]

        assert not [name for name in properties if "date" in name]

    def test_the_schema_offers_no_status(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """A retarget always lands on *not done*; there is nothing to choose."""
        assert "status" not in retarget_task_schema["input_schema"]["properties"]


class TestTheRetargetToolDocumentsItself:
    """A model only learns these rules from the schema it is given."""

    def test_the_tool_has_a_description(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        assert len(retarget_task_schema["description"]) > 0

    def test_the_description_says_a_done_task_is_reopened(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """Otherwise the refusal is the first the model hears of the rule."""
        description = retarget_task_schema["description"].lower()

        assert "done" in description
        assert "reopen" in description

    def test_the_description_says_this_is_the_way_out_of_cancelled(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """``set_task_status`` sends a model here; this is where it arrives."""
        description = retarget_task_schema["description"].lower()

        assert "cancelled" in description

    def test_the_due_journal_parameter_states_the_constraint(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """The future-dated rule is revalidated here, so it is stated here."""
        description = retarget_task_schema["input_schema"]["properties"][
            "due_journal_id"
        ]["description"]

        assert "future" in description.lower()

    def test_the_acknowledgement_parameter_says_what_it_confirms(
        self, retarget_task_schema: dict[str, Any]
    ) -> None:
        """A bare boolean is not a thing a model can decide to send."""
        description = retarget_task_schema["input_schema"]["properties"][
            "acknowledge_reopen"
        ]["description"].lower()

        assert "done" in description


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


@pytest.fixture
async def attach_journal_schema() -> dict[str, Any]:
    """``attach_intermediate_journal_to_task`` as an MCP client actually sees it."""
    return await _tool_schema("attach_intermediate_journal_to_task")


@pytest.fixture
async def detach_journal_schema() -> dict[str, Any]:
    """``detach_intermediate_journal_from_task`` as an MCP client sees it."""
    return await _tool_schema("detach_intermediate_journal_from_task")


class TestIntermediateJournalToolParameters:
    """What an AI client may send to attach or detach an intermediate journal."""

    def test_attaching_needs_a_task_and_a_journal(
        self, attach_journal_schema: dict[str, Any]
    ) -> None:
        required = set(attach_journal_schema["input_schema"]["required"])

        assert required == {"task_id", "journal_id"}

    def test_detaching_needs_a_task_and_a_journal(
        self, detach_journal_schema: dict[str, Any]
    ) -> None:
        required = set(detach_journal_schema["input_schema"]["required"])

        assert required == {"task_id", "journal_id"}

    def test_injected_collaborators_are_not_part_of_the_attach_contract(
        self, attach_journal_schema: dict[str, Any]
    ) -> None:
        properties = attach_journal_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties

    def test_injected_collaborators_are_not_part_of_the_detach_contract(
        self, detach_journal_schema: dict[str, Any]
    ) -> None:
        properties = detach_journal_schema["input_schema"]["properties"]

        assert "task_service" not in properties
        assert "db_connection" not in properties

    @pytest.mark.parametrize("parameter", ["task_id", "journal_id"])
    @pytest.mark.parametrize("tool", ["attach", "detach"])
    def test_both_ids_are_bounded_to_what_the_column_can_hold(
        self,
        attach_journal_schema: dict[str, Any],
        detach_journal_schema: dict[str, Any],
        tool: str,
        parameter: str,
    ) -> None:
        """An id past ``INTEGER`` used to be a 500 in asyncpg's parameter binding.

        The bound belongs in the schema rather than only in the service, because
        the transport refuses an out-of-range argument before any of this
        application's code runs — which is what turns a 500 into a rejection the
        model can read and correct.

        Both tools, which review caught: the earlier version read only the attach
        schema, so the detach tool's bounds were claimed and untested.
        """
        schemas = {"attach": attach_journal_schema, "detach": detach_journal_schema}
        schema = schemas[tool]["input_schema"]["properties"][parameter]

        assert schema["minimum"] == 1
        assert schema["maximum"] == 2147483647


class TestTheJournalLinkCarriesNoRole:
    """An intermediate link is a mention, and the schema has to say so.

    ``link_journal_to_contact`` takes a relationship type, a status and a role,
    so a model that has seen it will reach for the same arguments here. There are
    none to reach for, and the transport refuses what the schema does not offer —
    which is where the guarantee actually lives.
    """

    @pytest.mark.parametrize(
        "unwanted", ["relationship_type", "role", "status", "anchor", "now"]
    )
    def test_the_attach_schema_offers_no_role_or_seam(
        self, attach_journal_schema: dict[str, Any], unwanted: str
    ) -> None:
        assert unwanted not in attach_journal_schema["input_schema"]["properties"]

    @pytest.mark.parametrize(
        "unwanted", ["relationship_type", "role", "status", "anchor", "now"]
    )
    def test_the_detach_schema_offers_no_role_or_seam(
        self, detach_journal_schema: dict[str, Any], unwanted: str
    ) -> None:
        assert unwanted not in detach_journal_schema["input_schema"]["properties"]

    def test_neither_tool_offers_a_contact(
        self,
        attach_journal_schema: dict[str, Any],
        detach_journal_schema: dict[str, Any],
    ) -> None:
        """A journal link is not a contact link, and needs no contact at all."""
        for schema in (attach_journal_schema, detach_journal_schema):
            properties = schema["input_schema"]["properties"]
            assert not [name for name in properties if "contact" in name]


class TestTheJournalLinkToolsDocumentThemselves:
    """The docstring and the schema are these tools' only documentation.

    **No "has a description" test here, deliberately.** The contact-link tests
    above carry one and it cannot fail: the fixture already asserts the tool is
    registered, and a registered tool with no docstring is not something any
    edit to this module produces. What is worth asserting is that the two rules a
    model will otherwise learn from a rejection are stated *before* it sends one,
    so those are asserted by their content.
    """

    def test_the_attach_description_says_a_repeat_is_harmless(
        self, attach_journal_schema: dict[str, Any]
    ) -> None:
        """Otherwise an agent avoids a retry it is free to make.

        Asserted on the phrase rather than on the word "already", which review
        caught as a proxy loose enough to survive deleting the sentence — the
        parameter description says "must not *already* be the task's creating or
        due journal", so the word was present either way.
        """
        description = attach_journal_schema["description"].lower()

        assert "already attached is accepted" in description

    def test_the_attach_description_names_the_anchors_it_refuses(
        self, attach_journal_schema: dict[str, Any]
    ) -> None:
        """The most likely wrong call is attaching the journal it is due in.

        A model reaching for "link this task to its journal" will otherwise send
        the due journal, be refused, and have to learn the rule from the error.
        """
        description = attach_journal_schema["description"].lower()

        assert "due" in description
        assert "creating" in description

    def test_the_detach_description_says_the_anchors_cannot_be_removed(
        self, detach_journal_schema: dict[str, Any]
    ) -> None:
        """The rule the test's name promises, and the remedy that replaces it."""
        description = detach_journal_schema["description"].lower()

        assert "cannot be removed this way" in description
        assert "retarget" in description


@pytest.fixture
async def get_task_schema() -> dict[str, Any]:
    """The ``get_task`` tool as a client sees it."""
    return await _tool_schema("get_task")


@pytest.fixture
async def list_journal_tasks_schema() -> dict[str, Any]:
    """The ``list_journal_tasks`` tool as a client sees it."""
    return await _tool_schema("list_journal_tasks")


@pytest.mark.unit
class TestGetTaskToolParameters:
    """The read tool the write tools have been pointing at.

    Every task-returning tool so far carries the journal trail because "no tool
    reads a task back, so a trail left out of these answers would be unreachable
    rather than inconvenient". This is the tool that changes that, so its
    contract is the one an agent will reach for to check its own work.
    """

    def test_the_task_id_is_the_only_parameter(
        self, get_task_schema: dict[str, Any]
    ) -> None:
        """A read needs the id and nothing else."""
        input_schema = get_task_schema["input_schema"]

        assert input_schema["required"] == ["task_id"]
        assert list(input_schema["properties"]) == ["task_id"]

    def test_the_id_is_bounded_to_what_a_column_can_hold(
        self, get_task_schema: dict[str, Any]
    ) -> None:
        """An id no row could have is a bad request, not a 500."""
        task_id = get_task_schema["input_schema"]["properties"]["task_id"]

        assert task_id["minimum"] == 1
        assert task_id["maximum"] == 2_147_483_647

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, get_task_schema: dict[str, Any]
    ) -> None:
        """The connection and the service are wiring, not arguments."""
        properties = get_task_schema["input_schema"]["properties"]

        assert "db_connection" not in properties
        assert "task_read_service" not in properties

    @pytest.mark.parametrize("unwanted", ["now", "date", "today", "user_id"])
    def test_the_read_offers_no_seam_and_no_impersonation(
        self, get_task_schema: dict[str, Any], unwanted: str
    ) -> None:
        """ "Today" is the acting user's, resolved from their own settings.

        A tool able to set it could ask whether somebody else's task had
        lapsed, or whether this one had lapsed on a day of its choosing.
        """
        assert unwanted not in get_task_schema["input_schema"]["properties"]


@pytest.mark.unit
class TestGetTaskDocumentsWhatItReturns:
    """The docstring is the only place a model learns the answer's shape."""

    def test_it_says_the_journals_come_back_by_role(
        self, get_task_schema: dict[str, Any]
    ) -> None:
        """Three journal roles is not something to infer from a key name."""
        description = get_task_schema["description"].lower()

        assert "creating" in description
        assert "due" in description

    def test_it_explains_what_lapsed_means(
        self, get_task_schema: dict[str, Any]
    ) -> None:
        """A flag an agent cannot interpret is a flag it will act wrongly on.

        Both causes are named, because "the day went by" and "the meeting was
        called off" call for different follow-ups.
        """
        description = get_task_schema["description"].lower()

        assert "lapsed" in description
        assert "cancelled" in description

    def test_it_says_how_a_lapsed_task_is_resurrected(
        self, get_task_schema: dict[str, Any]
    ) -> None:
        """The one action that undoes a lapse, named where it is discovered."""
        assert "retarget" in get_task_schema["description"].lower()


@pytest.mark.unit
class TestListJournalTasksToolParameters:
    """Listing a journal's tasks, by the role each link holds."""

    def test_the_journal_id_is_required_and_the_role_is_not(
        self, list_journal_tasks_schema: dict[str, Any]
    ) -> None:
        """The default is the whole picture; the filter is opt-in."""
        input_schema = list_journal_tasks_schema["input_schema"]

        assert input_schema["required"] == ["journal_id"]
        assert "role" in input_schema["properties"]

    def test_the_role_offers_exactly_the_three_link_roles(
        self, list_journal_tasks_schema: dict[str, Any]
    ) -> None:
        """The specification's own vocabulary, so a model needs no glossary."""
        assert _enum_values(list_journal_tasks_schema["input_schema"], "role") == [
            "due",
            "created",
            "mentioned",
        ]

    def test_the_journal_id_is_bounded_to_what_a_column_can_hold(
        self, list_journal_tasks_schema: dict[str, Any]
    ) -> None:
        """The same bound every id on this surface carries."""
        journal_id = list_journal_tasks_schema["input_schema"]["properties"][
            "journal_id"
        ]

        assert journal_id["minimum"] == 1
        assert journal_id["maximum"] == 2_147_483_647

    @pytest.mark.parametrize("unwanted", ["now", "status", "page", "limit", "user_id"])
    def test_it_offers_no_seam_and_no_status_filter(
        self, list_journal_tasks_schema: dict[str, Any], unwanted: str
    ) -> None:
        """A journal shows the tasks it is linked to, whatever their status.

        The dashboard hides done, cancelled and lapsed ones; this surface does
        not, and a status filter here would invite an agent to reproduce the
        "everything still outstanding" browser the specification refuses.
        """
        assert unwanted not in list_journal_tasks_schema["input_schema"]["properties"]

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, list_journal_tasks_schema: dict[str, Any]
    ) -> None:
        """The connection and the service are wiring, not arguments."""
        properties = list_journal_tasks_schema["input_schema"]["properties"]

        assert "db_connection" not in properties
        assert "task_read_service" not in properties


@pytest.mark.unit
class TestListJournalTasksDocumentsItself:
    """What the three groups mean, said before an agent has to guess."""

    def test_it_names_all_three_groups(
        self, list_journal_tasks_schema: dict[str, Any]
    ) -> None:
        """Due here, created here, mentioned here."""
        description = list_journal_tasks_schema["description"].lower()

        assert "due" in description
        assert "created" in description
        assert "mentioned" in description

    def test_it_says_a_task_can_appear_in_two_groups(
        self, list_journal_tasks_schema: dict[str, Any]
    ) -> None:
        """Otherwise a counting agent double-counts and calls it a bug.

        One journal can be a task's creating and due anchor at once, and a
        retarget onto an already-mentioned journal makes the due anchor a
        mention as well.
        """
        assert "more than one group" in list_journal_tasks_schema["description"].lower()

    def test_it_says_lapsed_and_finished_tasks_are_included(
        self, list_journal_tasks_schema: dict[str, Any]
    ) -> None:
        """The difference from the dashboard, stated where it is acted on."""
        description = list_journal_tasks_schema["description"].lower()

        assert "lapsed" in description
        assert "every status" in description


@pytest.fixture
async def list_upcoming_tasks_schema() -> dict[str, Any]:
    """The ``list_upcoming_tasks`` tool as a client sees it."""
    return await _tool_schema("list_upcoming_tasks")


@pytest.mark.unit
class TestListUpcomingTasksToolParameters:
    """The forward window, which is the only listing that crosses journals.

    Its whole contract is one optional integer, so everything that makes the
    answer meaningful lives in the description rather than the schema — which
    is what the next class exists for. What the schema itself must do is refuse
    the things that would turn a bounded window into an unbounded task browser,
    or let an agent ask the question on somebody else's behalf.
    """

    def test_every_parameter_is_optional(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """ "What is coming up" is answerable with no arguments at all.

        The default is the specification's seven days, so an agent asked "what
        have I got on this week" sends an empty object.
        """
        input_schema = list_upcoming_tasks_schema["input_schema"]

        assert input_schema.get("required", []) == []
        assert list(input_schema["properties"]) == ["days_ahead"]

    def test_the_window_defaults_to_seven_days(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """The default is in the schema, not only in the prose.

        A model that reads the schema rather than the sentence must still send
        the same window the dashboard shows, or an agent and the UI will
        disagree about what "this week" holds.
        """
        days_ahead = list_upcoming_tasks_schema["input_schema"]["properties"][
            "days_ahead"
        ]

        assert days_ahead["default"] == 7

    def test_the_window_is_bounded_at_both_ends(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """Zero is today alone; the ceiling is what stops "every task ever".

        There is deliberately no unbounded task listing in this product, and an
        agent asking for a ten-year window would be one.
        """
        days_ahead = list_upcoming_tasks_schema["input_schema"]["properties"][
            "days_ahead"
        ]

        assert days_ahead["minimum"] == 0
        assert days_ahead["maximum"] == 90

    @pytest.mark.parametrize(
        "unwanted", ["now", "today", "date", "user_id", "status", "page", "limit"]
    )
    def test_it_offers_no_seam_no_impersonation_and_no_paging(
        self, list_upcoming_tasks_schema: dict[str, Any], unwanted: str
    ) -> None:
        """Three refusals in one list, for three different reasons.

        ``now``/``today``/``date``: the window is anchored on the acting user's
        today, and a tool able to move it could ask what next month will look
        like as though it were now. ``user_id``: the acting user is the session's.
        ``status``: the exclusions are the rule, not a default a caller may turn
        off. ``page``/``limit``: the window bounds the answer, and paging
        controls would advertise a collection this is not.
        """
        assert unwanted not in list_upcoming_tasks_schema["input_schema"]["properties"]

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """The connection and the service are wiring, not arguments."""
        properties = list_upcoming_tasks_schema["input_schema"]["properties"]

        assert "db_connection" not in properties
        assert "task_read_service" not in properties


@pytest.mark.unit
class TestListUpcomingTasksDocumentsItself:
    """Everything the one-integer schema cannot say.

    An agent that reads this listing without being told what is missing from it
    will report "you have nothing due" to a user with three lapsed commitments,
    which is worse than saying nothing at all.
    """

    def test_it_names_the_default_window(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """Seven days, so a model describing the answer names the right span."""
        assert "seven days" in list_upcoming_tasks_schema["description"].lower()

    def test_it_says_the_window_includes_today(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """The edge the future-dated rule excludes, so the two are easy to mix up."""
        description = list_upcoming_tasks_schema["description"].lower()

        assert "today" in description
        assert "inclusive" in description

    def test_it_says_whose_today_the_window_starts_on(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """The user's timezone, so an agent does not compute a window itself."""
        description = list_upcoming_tasks_schema["description"].lower()

        assert "timezone" in description
        assert "do not" in description

    def test_it_names_all_three_exclusions(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """Done, cancelled and lapsed — the ones an agent will otherwise miss."""
        description = list_upcoming_tasks_schema["description"].lower()

        assert "done" in description
        assert "cancelled" in description
        assert "lapsed" in description

    def test_it_says_where_the_excluded_tasks_can_still_be_found(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """An absent task is not a deleted one, and the tool says which is which.

        ``list_journal_tasks`` lists every status, so it is the answer to "where
        did that commitment go" — named here because that is where the question
        is asked.
        """
        description = list_upcoming_tasks_schema["description"].lower()

        assert "list_journal_tasks" in description
        assert "retarget" in description

    def test_it_says_the_answer_is_the_whole_window(
        self, list_upcoming_tasks_schema: dict[str, Any]
    ) -> None:
        """No paging, so an agent does not go looking for a second page."""
        assert "not paginated" in list_upcoming_tasks_schema["description"].lower()


@pytest.fixture
async def get_task_history_schema() -> dict[str, Any]:
    """The ``get_task_history`` tool as an MCP client actually sees it."""
    return await _tool_schema("get_task_history")


class TestGetTaskHistoryToolParameters:
    """What an AI client may send, and what it must not have to."""

    def test_only_the_task_is_required(
        self, get_task_history_schema: dict[str, Any]
    ) -> None:
        """Paging is optional, so the first call is one argument."""
        schema = get_task_history_schema["input_schema"]

        assert set(schema["required"]) == {"task_id"}
        assert {"task_id", "page", "limit"} <= set(schema["properties"])

    def test_the_page_size_is_capped_in_the_schema(
        self, get_task_history_schema: dict[str, Any]
    ) -> None:
        """The cap is part of the contract, not a surprise the tool raises.

        A model that reads the bound asks for a legal page; one that discovers
        it by rejection burns a call and may report the failure to the user.
        """
        limit = get_task_history_schema["input_schema"]["properties"]["limit"]

        assert limit["maximum"] == 100
        assert limit["minimum"] == 1

    def test_pages_start_at_one(self, get_task_history_schema: dict[str, Any]) -> None:
        page = get_task_history_schema["input_schema"]["properties"]["page"]

        assert page["minimum"] == 1

    def test_injected_collaborators_are_not_part_of_the_contract(
        self, get_task_history_schema: dict[str, Any]
    ) -> None:
        properties = get_task_history_schema["input_schema"]["properties"]

        assert "history_service" not in properties
        assert "db_connection" not in properties


class TestGetTaskHistoryToolDescription:
    """What the one-integer schema cannot say, and an agent would get wrong."""

    def test_it_says_the_entries_are_most_recent_first(
        self, get_task_history_schema: dict[str, Any]
    ) -> None:
        """An agent summarising a history in the wrong order tells the user the
        opposite story about what happened."""
        assert "most recent first" in get_task_history_schema["description"].lower()

    def test_it_says_history_lags_the_change(
        self, get_task_history_schema: dict[str, Any]
    ) -> None:
        """Projection is asynchronous. An agent that made a change and reads the
        history back immediately may not see its own edit, and must not conclude
        the edit failed."""
        description = get_task_history_schema["description"].lower()

        assert "asynchronous" in description or "moment" in description

    def test_it_says_a_deleted_task_still_has_a_history(
        self, get_task_history_schema: dict[str, Any]
    ) -> None:
        """The one thing about this tool that differs from every other task
        tool: it answers for an id that ``get_task`` reports as not found. An
        agent that does not know this will not think to ask."""
        assert "delete" in get_task_history_schema["description"].lower()

    def test_it_says_this_is_a_record_rather_than_a_task_listing(
        self, get_task_history_schema: dict[str, Any]
    ) -> None:
        """The specification's "no third working surface" rule, said where an
        agent might otherwise try to assemble one out of history reads."""
        assert "record" in get_task_history_schema["description"].lower()
