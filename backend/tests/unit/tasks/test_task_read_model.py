"""Unit tests for the task read model and its assembler.

The read model is what every read surface hands out: the task, its journals
**by role**, its contacts, and whether it has lapsed and why. It is assembled by
a pure function over pieces someone else has already fetched — which is the
whole point of the split. A list surface fetches *N* tasks' journals in one
query and calls this once per task; nothing here can issue a query, so nothing
here can turn a list into an N+1.

The assembler takes the two anchors as **arguments** rather than looking them up
in a map of journals, so a caller cannot hand it a read model missing the due
journal — which is the one piece the lapsed rule cannot do without. Resolving an
id to a journal, and deciding what a missing one means, is the service's job.
"""

import datetime

import pytest
from core_shared.models.tasks import (
    LapseReason,
    TaskContactRef,
    TaskJournalRef,
    TaskReadModel,
    TaskStatus,
    build_task_read_model,
)

from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    make_task,
)

TODAY = datetime.date(2026, 8, 9)
YESTERDAY = datetime.date(2026, 8, 8)
TOMORROW = datetime.date(2026, 8, 10)

MENTIONED_JOURNAL_ID = 33
ALSO_MENTIONED_JOURNAL_ID = 44


def journal_ref(
    journal_id: int,
    *,
    title: str = "Permit Meeting",
    date: datetime.date = TOMORROW,
    cancelled: bool = False,
) -> TaskJournalRef:
    """One journal as a read surface sees it."""
    return TaskJournalRef(id=journal_id, title=title, date=date, cancelled=cancelled)


def build(
    *,
    status: TaskStatus = TaskStatus.NOT_DONE,
    creating: TaskJournalRef | None = None,
    due: TaskJournalRef | None = None,
    intermediates: tuple[TaskJournalRef, ...] = (),
    contacts: tuple[TaskContactRef, ...] = (),
) -> TaskReadModel:
    """Assemble a read model, defaulting everything a case does not care about."""
    return build_task_read_model(
        task=make_task(status),
        creating_journal=creating
        or journal_ref(CREATING_JOURNAL_ID, title="Monday Planning", date=YESTERDAY),
        due_journal=due or journal_ref(DUE_JOURNAL_ID),
        intermediate_journals=intermediates,
        contacts=contacts,
        today=TODAY,
    )


@pytest.mark.unit
class TestJournalsByRole:
    """The three roles the specification names, kept apart."""

    def test_each_journal_lands_under_its_own_role(self) -> None:
        """Creating, due and mentioned are three separate places on the model."""
        model = build(
            intermediates=(journal_ref(MENTIONED_JOURNAL_ID, title="Standup"),)
        )

        assert model.creating_journal.id == CREATING_JOURNAL_ID
        assert model.due_journal.id == DUE_JOURNAL_ID
        assert [ref.id for ref in model.intermediate_journals] == [MENTIONED_JOURNAL_ID]

    def test_one_journal_may_be_both_anchors(self) -> None:
        """Invariant 6: creating and due may be the same journal.

        Both roles report it rather than one of them collapsing, because a
        surface grouping tasks by role must show the task under both headings.
        """
        shared = journal_ref(CREATING_JOURNAL_ID, title="Trip Planning")

        model = build(creating=shared, due=shared)

        assert model.creating_journal is model.due_journal
        assert model.due_journal.id == CREATING_JOURNAL_ID

    def test_a_journal_that_is_the_due_anchor_and_a_mention_appears_as_both(
        self,
    ) -> None:
        """The retarget-onto-an-attached-journal shape, carried faithfully.

        The intermediate link stays removable while the journal is also the
        due anchor. Hiding it here would leave the read model disagreeing with
        the surface that can delete it.
        """
        due = journal_ref(DUE_JOURNAL_ID)

        model = build(due=due, intermediates=(due,))

        assert model.due_journal.id == DUE_JOURNAL_ID
        assert [ref.id for ref in model.intermediate_journals] == [DUE_JOURNAL_ID]

    def test_intermediate_journals_keep_the_order_they_arrive_in(self) -> None:
        """Oldest link first, as the repository lists them — not re-sorted here."""
        first = journal_ref(ALSO_MENTIONED_JOURNAL_ID, title="First mention")
        second = journal_ref(MENTIONED_JOURNAL_ID, title="Second mention")

        model = build(intermediates=(first, second))

        assert [ref.id for ref in model.intermediate_journals] == [
            ALSO_MENTIONED_JOURNAL_ID,
            MENTIONED_JOURNAL_ID,
        ]

    def test_a_journal_ref_carries_the_id_title_and_local_date(self) -> None:
        """Enough to render a link and a date without a second lookup.

        The date is already resolved in the user's timezone — the ref holds a
        ``date``, not an instant, so no surface can re-derive it in the wrong
        zone.
        """
        ref = journal_ref(DUE_JOURNAL_ID, title="Permit Meeting", date=TOMORROW)

        model = build(due=ref)

        assert model.due_journal.title == "Permit Meeting"
        assert model.due_journal.date == TOMORROW
        assert model.due_journal.cancelled is False


@pytest.mark.unit
class TestContacts:
    """Contacts are a plain reference — no role, no relationship type."""

    def test_contacts_are_carried_in_link_order_with_their_names(self) -> None:
        """Everything a row needs to show a person, in the order they were linked."""
        sarah = TaskContactRef(
            id=5, display_name="Sarah Chen", photo_url="https://example.com/s.jpg"
        )
        mo = TaskContactRef(id=9, display_name="Mo Farah", photo_url=None)

        model = build(contacts=(sarah, mo))

        assert model.contacts == (sarah, mo)
        assert model.contacts[0].display_name == "Sarah Chen"
        assert model.contacts[1].photo_url is None

    def test_a_task_with_no_links_gets_empty_tuples_not_none(self) -> None:
        """An empty collection is empty, so no surface needs a null check."""
        model = build()

        assert model.intermediate_journals == ()
        assert model.contacts == ()


@pytest.mark.unit
class TestLapseOnTheModel:
    """The rule's answer, reached through the model a surface actually holds."""

    def test_a_passed_due_date_lapses_the_assembled_model(self) -> None:
        """The date cause, derived from the due journal's ref."""
        model = build(due=journal_ref(DUE_JOURNAL_ID, date=YESTERDAY))

        assert model.lapse_reason == LapseReason.DATE_PASSED

    def test_a_cancelled_due_journal_lapses_the_assembled_model(self) -> None:
        """The cancellation cause, derived from the due journal's ref."""
        model = build(due=journal_ref(DUE_JOURNAL_ID, cancelled=True))

        assert model.lapse_reason == LapseReason.DUE_JOURNAL_CANCELLED

    def test_only_the_due_journal_decides_it(self) -> None:
        """A passed creating journal and a cancelled mention lapse nothing.

        The default creating journal is already dated yesterday, so this case
        adds a cancelled mention beside it: neither is the commitment's moment,
        and treating either as one would lapse most tasks the day after they
        were made.
        """
        model = build(
            intermediates=(journal_ref(MENTIONED_JOURNAL_ID, cancelled=True),)
        )

        assert model.lapse_reason is None

    def test_lapsed_is_exactly_whether_there_is_a_reason(self) -> None:
        """The boolean a surface asks for, with no second definition behind it."""
        lapsed = build(due=journal_ref(DUE_JOURNAL_ID, date=YESTERDAY))
        outstanding = build()

        assert lapsed.lapsed is True
        assert outstanding.lapsed is False

    def test_a_done_task_is_not_lapsed_through_the_model_either(self) -> None:
        """The status gate holds at this level too, not only in the bare rule."""
        model = build(
            status=TaskStatus.DONE,
            due=journal_ref(DUE_JOURNAL_ID, date=YESTERDAY, cancelled=True),
        )

        assert model.lapse_reason is None
        assert model.lapsed is False


@pytest.mark.unit
class TestTheTaskItself:
    """The read model wraps the entity rather than flattening it."""

    def test_the_task_is_carried_whole(self) -> None:
        """Text, status and both anchor ids stay reachable, unduplicated."""
        model = build()

        assert model.task.id == make_task().id
        assert model.task.text == make_task().text
        assert model.task.status is TaskStatus.NOT_DONE
