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

from app.api.tasks.controllers import (
    delete_task,
    get_task,
    get_task_history,
    list_journal_tasks,
    list_upcoming_tasks,
    update_task,
)


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


@pytest.mark.unit
class TestTheReadEndpointsDocumentWhatTheyAnswer:
    """The two reads publish their own contract through FastAPI.

    A read's 404 is worth stating for the reason the write endpoints' are: a
    task that is not yours and one that never existed answer identically, so a
    client that does not know that will read the 404 as "deleted" and act on it.
    """

    def test_the_single_read_documents_its_404(self) -> None:
        """Unknown and not-yours are one answer, deliberately."""
        description = _description(get_task)

        assert "404" in description
        assert "yours" in description

    def test_the_single_read_says_the_lapse_is_derived_on_every_read(self) -> None:
        """Never stored, so a caller does not go looking for a column.

        Asserted on the phrase rather than on the word "lapsed", which appears
        in the payload description either way: a rewrite that dropped the
        "derived on every read and never stored" sentence would otherwise leave
        this green while removing the only place a client learns there is no
        column to poll.
        """
        description = _description(get_task)

        assert "derived on every read" in description
        assert "never stored" in description

    def test_the_journal_listing_names_the_three_groups(self) -> None:
        """The specification's vocabulary, published as the endpoint's own."""
        description = _description(list_journal_tasks)

        assert "due" in description
        assert "created" in description
        assert "mentioned" in description

    def test_the_journal_listing_documents_its_404(self) -> None:
        """A journal that is not yours is a journal that is not there.

        Asserted on "yours" as well as the status, as the single read's case
        does: the status alone is near-certain to appear anyway, and the part
        worth documenting is that an unowned journal and an absent one are one
        answer — which is what stops a client reading a 404 as "deleted", and
        what stops a rejection being used to probe for other users' journals.
        """
        description = _description(list_journal_tasks)

        assert "404" in description
        assert "yours" in description

    def test_the_journal_listing_says_a_task_may_hold_two_roles(self) -> None:
        """Otherwise the once-in-``data`` shape reads as a missing row."""
        description = _description(list_journal_tasks)

        assert "more than one group" in description


@pytest.mark.unit
class TestTheUpcomingListingDocumentsItsWindow:
    """The listing whose whole contract is a rule the schema cannot state.

    Its parameter is one integer with a default, so everything that makes the
    answer meaningful — where the window starts, which tasks are missing from it
    and why, and whose clock decides — exists only in the description. A client
    that does not read it will see a task vanish from the listing and conclude
    the task was deleted.
    """

    def test_it_names_the_default_window(self) -> None:
        """Seven days, the specification's own figure."""
        description = _description(list_upcoming_tasks)

        assert "seven days" in description

    def test_it_says_the_window_includes_today(self) -> None:
        """The near edge, which the future-dated invariant excludes.

        The two rules disagree about today on purpose, and a caller who assumes
        this one matches the create rule will think today's tasks are missing.
        """
        description = _description(list_upcoming_tasks)

        assert "today" in description
        assert "inclusive" in description

    def test_it_says_the_window_is_anchored_in_the_users_timezone(self) -> None:
        """So a client does not re-derive "today" in the browser's zone.

        Asserted on "timezone" together with the anchoring word rather than on
        "timezone" alone, which the date fields' own descriptions would satisfy.
        """
        description = _description(list_upcoming_tasks)

        assert "your timezone" in description
        assert "anchored" in description

    def test_it_names_all_three_exclusions(self) -> None:
        """Done, cancelled and lapsed, because an absence is otherwise a puzzle."""
        description = _description(list_upcoming_tasks)

        assert "done" in description
        assert "cancelled" in description
        assert "lapsed" in description

    def test_it_says_where_an_excluded_task_can_still_be_found(self) -> None:
        """A lapsed task is hidden here and visible on its journals.

        The half that makes the exclusion safe to document: without it, "lapsed
        tasks do not appear" reads as data loss rather than as a deliberate
        split between two surfaces.
        """
        description = _description(list_upcoming_tasks)

        assert "journal" in description
        assert "retarget" in description

    def test_it_says_the_window_is_uncapped(self) -> None:
        """The choice ITER18-004's show-more depends on.

        The whole window travels in one response, so revealing the rest of it
        costs no second request. A client told nothing would reasonably
        implement pagination against an endpoint that has none.
        """
        description = _description(list_upcoming_tasks)

        assert "not paginated" in description


@pytest.mark.unit
class TestTheHistoryEndpointDocumentsWhatMakesItDifferent:
    """Three claims that are only true of *this* endpoint, and only in prose.

    Every other history read in this API answers 404 for an id whose entity is
    gone, and none of them has to explain why an empty answer is not a refusal.
    A client generated from the OpenAPI description gets no hint of either from
    the schema — both are 200s carrying the same shape — so if the description
    does not say them, nobody reading `/docs` learns them.

    The MCP half of this is asserted in
    ``tests/unit/mcp/domains/test_task_tools_schema.py``; this is the REST half,
    for the same reason the delete stance above has both.
    """

    def test_it_says_a_deleted_tasks_history_is_still_readable(self) -> None:
        """The one behaviour that contradicts every other route in this file.

        ``GET /api/tasks/{id}`` answers 404 for the same id this route answers
        200 for. A client author who does not know that will treat a successful
        history read for a "missing" task as a bug in the API.
        """
        description = _description(get_task_history)

        assert "deleted" in description
        assert "hard-deleted" in description or "hard deleted" in description

    def test_it_says_an_empty_history_is_not_a_missing_task(self) -> None:
        """Projection is asynchronous, so this is the ordinary case immediately
        after a task is created — and the answer a client must not retry on."""
        description = _description(get_task_history)

        assert "404" in description
        assert "moment" in description or "asynchronous" in description

    def test_it_says_this_is_a_record_rather_than_a_task_browser(self) -> None:
        """The specification's "no third working surface" rule, said where
        somebody looking for a task listing would go looking for one."""
        description = _description(get_task_history)

        assert "record" in description
        assert "no collection" in description
