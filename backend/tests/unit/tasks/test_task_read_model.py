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
    TaskAnchorMissingError,
    TaskContactRef,
    TaskIcon,
    TaskJournalRef,
    TaskListRef,
    TaskReadModel,
    TaskStatus,
    build_task_read_model,
)

from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    TASK_LIST_ID,
    make_list_task,
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
    last_day: datetime.date | None = None,
    cancelled: bool = False,
) -> TaskJournalRef:
    """One journal as a read surface sees it; single-day unless ``last_day``."""
    return TaskJournalRef(
        id=journal_id,
        title=title,
        date=date,
        last_day=date if last_day is None else last_day,
        cancelled=cancelled,
    )


PACKING = TaskListRef(
    id=TASK_LIST_ID, name="Packing", icon=TaskIcon.PACKAGE, archived=False
)


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
        task_list=None,
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

        assert model.require_journal("creating").id == CREATING_JOURNAL_ID
        assert model.require_journal("due").id == DUE_JOURNAL_ID
        assert [ref.id for ref in model.intermediate_journals] == [MENTIONED_JOURNAL_ID]

    def test_one_journal_may_be_both_anchors(self) -> None:
        """Invariant 6: creating and due may be the same journal.

        Both roles report it rather than one of them collapsing, because a
        surface grouping tasks by role must show the task under both headings.
        """
        shared = journal_ref(CREATING_JOURNAL_ID, title="Trip Planning")

        model = build(creating=shared, due=shared)

        assert model.creating_journal is model.due_journal
        assert model.require_journal("due").id == CREATING_JOURNAL_ID

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

        assert model.require_journal("due").id == DUE_JOURNAL_ID
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

        assert model.require_journal("due").title == "Permit Meeting"
        assert model.require_journal("due").date == TOMORROW
        assert model.require_journal("due").cancelled is False


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


def build_list_task(
    *,
    creating: TaskJournalRef | None = None,
    due: TaskJournalRef | None = None,
    due_date: datetime.date | None = None,
    status: TaskStatus = TaskStatus.NOT_DONE,
    today: datetime.date = TODAY,
) -> TaskReadModel:
    """Assemble a list task's read model, with only the journals it holds."""
    return build_task_read_model(
        task=make_list_task(
            status,
            creating_journal_id=creating.id if creating else None,
            due_journal_id=due.id if due else None,
            due_date=due_date,
        ),
        creating_journal=creating,
        due_journal=due,
        intermediate_journals=(),
        contacts=(),
        task_list=PACKING,
        today=today,
    )


@pytest.mark.unit
class TestAListTask:
    """A task on a list may have no journal, one of the two, or both."""

    def test_a_list_task_with_no_journal_has_no_refs_and_is_not_lapsed(
        self,
    ) -> None:
        """Both refs are absent, and with no due journal nothing can lapse."""
        model = build_list_task()

        assert model.creating_journal is None
        assert model.due_journal is None
        assert model.lapse_reason is None
        assert model.lapsed is False

    def test_a_list_task_with_only_a_due_journal_keeps_that_ref(self) -> None:
        """The due journal it has is carried; the creating one stays absent."""
        due = journal_ref(DUE_JOURNAL_ID)

        model = build_list_task(due=due)

        assert model.creating_journal is None
        assert model.due_journal is due

    def test_a_list_task_with_only_a_creating_journal_keeps_that_ref(self) -> None:
        """The journal it arose in is carried; it has no due journal."""
        creating = journal_ref(CREATING_JOURNAL_ID, date=YESTERDAY)

        model = build_list_task(creating=creating)

        assert model.creating_journal is creating
        assert model.due_journal is None

    def test_a_list_task_due_in_a_passed_journal_is_not_lapsed(self) -> None:
        """Invariant 7: a late list task is overdue, never lapsed."""
        model = build_list_task(due=journal_ref(DUE_JOURNAL_ID, date=YESTERDAY))

        assert model.lapse_reason is None

    def test_a_list_task_due_in_a_cancelled_journal_is_not_lapsed(self) -> None:
        """A cancelled due journal does not lapse a list task either."""
        model = build_list_task(due=journal_ref(DUE_JOURNAL_ID, cancelled=True))

        assert model.lapse_reason is None


@pytest.mark.unit
class TestRequireJournal:
    """The narrowing a journal-only surface reads a ref through."""

    def test_it_returns_the_ref_in_each_role(self) -> None:
        """A journal-only task has both, and each comes back as itself."""
        model = build()

        assert model.require_journal("creating") is model.creating_journal
        assert model.require_journal("due") is model.due_journal

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    def test_it_raises_for_an_absent_ref(self, anchor: str) -> None:
        """A missing ref on a journal-only path is a broken invariant."""
        model = build_list_task()

        with pytest.raises(TaskAnchorMissingError) as raised:
            model.require_journal(anchor)  # type: ignore[arg-type]

        assert raised.value.anchor == anchor
        assert raised.value.task_id == model.task.id


@pytest.mark.unit
class TestTheList:
    """The list a task is on, carried as a ref a surface can label and link."""

    def test_a_list_task_carries_its_list(self) -> None:
        """Id, name, icon and archived state, with no second lookup."""
        model = build_list_task()

        assert model.task_list == PACKING

    def test_a_journal_only_task_has_no_list(self) -> None:
        """No list, no ref."""
        assert build().task_list is None

    def test_a_list_ref_for_another_list_is_refused(self) -> None:
        """A ref that does not name the task's own list is a caller's bug."""
        other = TaskListRef(
            id=TASK_LIST_ID + 1, name="Other", icon=None, archived=False
        )

        with pytest.raises(ValueError, match="task_list"):
            build_task_read_model(
                task=make_list_task(),
                creating_journal=None,
                due_journal=None,
                intermediate_journals=(),
                contacts=(),
                task_list=other,
                today=TODAY,
            )

    def test_a_list_task_without_its_list_ref_is_refused(self) -> None:
        """Leaving the ref out for a task on a list is the same bug."""
        with pytest.raises(ValueError, match="task_list"):
            build_task_read_model(
                task=make_list_task(),
                creating_journal=None,
                due_journal=None,
                intermediate_journals=(),
                contacts=(),
                task_list=None,
                today=TODAY,
            )

    def test_a_list_ref_on_a_journal_only_task_is_refused(self) -> None:
        """A journal-only task cannot be labelled with a list."""
        with pytest.raises(ValueError, match="task_list"):
            build_task_read_model(
                task=make_task(),
                creating_journal=journal_ref(CREATING_JOURNAL_ID, date=YESTERDAY),
                due_journal=journal_ref(DUE_JOURNAL_ID),
                intermediate_journals=(),
                contacts=(),
                task_list=PACKING,
                today=TODAY,
            )


@pytest.mark.unit
class TestOverdueOnTheModel:
    """Overdue, read from the one date rule every task goes through."""

    def test_a_due_date_before_today_is_overdue(self) -> None:
        """Past its date, a list task is overdue rather than lapsed."""
        model = build_list_task(due_date=YESTERDAY)

        assert model.overdue is True
        assert model.lapsed is False

    def test_a_due_date_of_today_is_not_overdue(self) -> None:
        """Due today is outstanding, not late."""
        assert build_list_task(due_date=TODAY).overdue is False

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    def test_a_closed_list_task_is_never_overdue(self, status: TaskStatus) -> None:
        """The marker lasts only until the task is done or cancelled."""
        assert build_list_task(due_date=YESTERDAY, status=status).overdue is False

    def test_a_passed_due_journal_makes_a_list_task_overdue(self) -> None:
        """A due journal dates the task as a due date would."""
        model = build_list_task(due=journal_ref(DUE_JOURNAL_ID, date=YESTERDAY))

        assert model.overdue is True
        assert model.lapsed is False

    def test_a_multi_day_due_journal_is_not_overdue_on_its_last_day(self) -> None:
        """A trip that started two days ago and ends today is not yet over."""
        trip = journal_ref(
            DUE_JOURNAL_ID, date=TODAY - datetime.timedelta(days=2), last_day=TODAY
        )

        assert build_list_task(due=trip).overdue is False

    def test_a_multi_day_due_journal_is_overdue_after_its_last_day(self) -> None:
        """Once the trip's last day has ended, the task is overdue."""
        trip = journal_ref(
            DUE_JOURNAL_ID,
            date=TODAY - datetime.timedelta(days=3),
            last_day=YESTERDAY,
        )

        assert build_list_task(due=trip).overdue is True

    def test_a_cancelled_due_journal_leaves_a_list_task_undated(self) -> None:
        """Undated while cancelled: neither overdue nor lapsed."""
        model = build_list_task(
            due=journal_ref(DUE_JOURNAL_ID, date=YESTERDAY, cancelled=True)
        )

        assert model.overdue is False
        assert model.lapsed is False

    def test_a_list_task_with_no_date_at_all_is_not_overdue(self) -> None:
        """No due date and no due journal — as after its due journal was
        deleted — is simply undated."""
        model = build_list_task(
            creating=journal_ref(CREATING_JOURNAL_ID, date=YESTERDAY)
        )

        assert model.overdue is False
        assert model.lapsed is False

    def test_a_journal_only_task_is_never_overdue(self) -> None:
        """Past its due journal it lapses, as it always has."""
        model = build(due=journal_ref(DUE_JOURNAL_ID, date=YESTERDAY))

        assert model.overdue is False
        assert model.lapse_reason == LapseReason.DATE_PASSED

    def test_a_journal_only_task_waits_out_its_due_journals_last_day(self) -> None:
        """A journal-only task lapses only once its due journal has ended.

        The same day a list task becomes overdue: under way, it is live and
        neither lapsed nor overdue.
        """
        trip = journal_ref(DUE_JOURNAL_ID, date=YESTERDAY, last_day=TOMORROW)

        model = build(due=trip)

        assert model.lapse_reason is None
        assert model.overdue is False
