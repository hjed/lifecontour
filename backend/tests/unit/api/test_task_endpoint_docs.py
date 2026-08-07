"""Unit tests for what the task endpoints' own documentation must say.

Prose is not normally worth a test. This is the exception, because one of Phase
9's acceptance criteria *is* prose: "**both** docstrings make cancel the ordinary
action and delete the exception, consistent with the journals specification's
stance". The specification wants hard deletion available but not led with, and
nothing in a transport can express a preference — 204 is 204 either way. The
preference lives entirely in what the two surfaces say, so if it is not asserted
it is not delivered, and deleting the paragraph would leave the suite green.

The MCP half is asserted in ``tests/unit/mcp/domains/test_task_tools_schema.py``
against the generated tool schema. This is the REST half. A controller
docstring is not decoration here either: FastAPI publishes it verbatim as the
endpoint's OpenAPI ``description``, so it is what a generated client, a
documentation page and anyone reading `/docs` sees.
"""

import pytest

from app.api.tasks.controllers import delete_task, update_task


def _description(endpoint: object) -> str:
    """The endpoint's docstring, which FastAPI publishes as its description."""
    doc: str | None = getattr(endpoint, "__doc__", None)
    assert doc, "the endpoint must be documented to be documented correctly"
    return doc.lower()


@pytest.mark.unit
class TestDeleteLeadsWithCancelling:
    """Acceptance criterion 3, REST half."""

    def test_the_summary_line_itself_steers_to_cancelling(self) -> None:
        """The first line is what a client library and `/docs` show in a list.

        Asserted on the whole phrase rather than on the word "cancel", which
        also appears inside "cancelled" — a description reading "deleting is
        tidier than cancelling" would satisfy the looser check while saying the
        opposite of the criterion.
        """
        first_line = (delete_task.__doc__ or "").strip().splitlines()[0].lower()

        assert "prefer cancelling" in first_line

    def test_it_names_the_operation_that_cancels(self) -> None:
        """Naming the alternative in the abstract is not something to act on."""
        description = _description(delete_task)

        assert "status" in description
        assert "cancelled" in description

    def test_it_says_the_deletion_is_permanent(self) -> None:
        """The asymmetry between the two is the whole reason to prefer one."""
        description = _description(delete_task)

        assert "permanent" in description

    def test_it_says_what_survives_the_deletion(self) -> None:
        """A user must not be warned that their journals are at risk.

        Both anchors in particular: deleting the task is the supported way to
        unblock a journal deletion a task was holding up.
        """
        description = _description(delete_task)

        assert "untouched" in description
        assert "journals" in description
        assert "contacts" in description


@pytest.mark.unit
class TestTheUpdateEndpointDocumentsItsOptionality:
    """The one thing a client cannot discover from the schema alone."""

    def test_it_says_text_and_status_are_both_optional_and_one_is_required(
        self,
    ) -> None:
        """A ``model_validator`` failure is a 422-shaped surprise otherwise."""
        description = _description(update_task)

        assert "optional" in description
        assert "at least one" in description
