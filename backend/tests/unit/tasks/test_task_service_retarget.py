"""Unit tests for ``TaskService.retarget_due_journal``.

Retargeting is the specification's one *automatic link* and its only way back
out of a terminal status, so it carries more rules than any other task
operation. Each of them is pinned here against mocked repositories:

- **the future-dated and ownership rules are revalidated at set time**, whatever
  the task's current status — a lapsed or cancelled task is not exempt from the
  rule that a due journal must be a real, future, owned journal;
- **the previous due journal is retained as an intermediate journal**, which is
  the model's only link the user did not ask for, so that the trail of a
  repeatedly-deferred task stays visible on the journals it passed through;
- **retargeting always lands on not done** — not done stays, cancelled is
  reopened, done is reopened;
- **reopening a done task needs an explicit acknowledgement**, because moving a
  date is rarely how a user means to undo a completion;
- **the creating journal is immutable**, enforced by there being no parameter
  that could set it.

The date cases use fixed instants and an injected ``now`` rather than offsets
from the real clock, for the reason Phase 3 recorded: the behaviour under test is
the instant-to-local-date derivation, and there is no ``freezegun`` in this repo.
``JournalDateResolver`` is the **real** collaborator over a mocked settings
repository, because the timezone rule is part of the behaviour being tested.
"""

import datetime
import inspect
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, call

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDomainError,
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatus,
    TaskStatusTransitionError,
)
from sqlalchemy.exc import IntegrityError

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.models.events import DomainEvent
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import published_events

USER_ID = "test-user-123"
OTHER_USER_ID = "other-user-456"

TASK_ID = 7
CREATING_JOURNAL_ID = 11
OLD_DUE_JOURNAL_ID = 22
NEW_DUE_JOURNAL_ID = 33

TASK_TEXT = "return Sarah's book"

SYDNEY = "Australia/Sydney"

# A fixed "now" and the local dates around it, so every date case reads as
# arithmetic against one instant rather than against the wall clock.
NOW = datetime.datetime(2026, 8, 5, 12, 0, tzinfo=datetime.UTC)
TODAY = datetime.date(2026, 8, 5)
TOMORROW = datetime.date(2026, 8, 6)
YESTERDAY = datetime.date(2026, 8, 4)

# Late enough in the UTC day that Sydney (+10) has already turned the page: the
# same instant is the 5th in UTC and the 6th in Sydney, which is what lets a
# timezone assertion be made without a second clock.
NOW_SYDNEY_IS_TOMORROW = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)

ALL_STATUSES = list(TaskStatus)


def at(day: datetime.date, hour: int = 9) -> datetime.datetime:
    """A UTC instant on ``day``, the way the database hands timestamps back."""
    return datetime.datetime(day.year, day.month, day.day, hour, tzinfo=datetime.UTC)


def make_journal(
    journal_id: int,
    start: datetime.datetime,
    *,
    title: str = "A journal",
) -> Journal:
    """An instantaneous journal on ``start``."""
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title=title,
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


def make_task(
    status: TaskStatus = TaskStatus.NOT_DONE,
    *,
    due_journal_id: int = OLD_DUE_JOURNAL_ID,
    creating_journal_id: int = CREATING_JOURNAL_ID,
) -> Task:
    """A persisted task in ``status``, as the repository would hand it back."""
    return Task(
        id=TASK_ID,
        user_id=USER_ID,
        text=TASK_TEXT,
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        status=status,
        created_at=at(YESTERDAY),
        updated_at=at(YESTERDAY),
    )


@pytest.fixture
def new_due_journal() -> Journal:
    """A future-dated journal, valid as the retarget target."""
    return make_journal(NEW_DUE_JOURNAL_ID, at(TOMORROW), title="Where it matters now")


@pytest.fixture
def mock_task_repo() -> AsyncMock:
    """A task repository that echoes back whatever it is asked to save.

    A retarget reads the task **twice**: a non-locking peek that learns which
    journal it is leaving, and the locking read that every decision is then made
    from. Unless a test says otherwise the two agree, so the peek is wired to
    report whatever the locking read is configured to return and a test that
    only cares about the task's state still has one place to set it. The tests
    that need them to *disagree* — which is what a concurrent writer between
    them looks like — use :func:`stored_task`.
    """
    repo = AsyncMock()

    async def save(task: Task) -> Task:
        return task

    async def peek(_task_id: int, _user_id: str) -> Task | None:
        found = repo.find_by_id_for_update.return_value
        return found if isinstance(found, Task) else None

    repo.save.side_effect = save
    repo.find_by_id_for_update.return_value = make_task()
    repo.find_by_id.side_effect = peek
    repo.add_intermediate_journal.return_value = True
    return repo


def stored_task(repo: AsyncMock, *, peeked: Task | None, locked: Task | None) -> None:
    """Make the retarget's two reads of the task disagree.

    The gap between the peek and the locking read is exactly where another
    writer's commit lands, so it is the only place these two can differ — and
    every rule the retarget applies has to come from ``locked``.
    """
    repo.find_by_id.side_effect = None
    repo.find_by_id.return_value = peeked
    repo.find_by_id_for_update.return_value = locked


@pytest.fixture
def mock_journal_repo(new_due_journal: Journal) -> AsyncMock:
    """A journal repository holding the target journal, owner-scoped like the real one.

    The retarget reads journals through the **ordered locking read**
    ``find_and_lock_by_ids_for_user``, which is what puts the journal locks in
    front of the task lock; the plain ``find_by_ids_for_user`` is no longer on
    this path at all.
    """
    repo = AsyncMock()
    repo.find_and_lock_by_ids_for_user.return_value = [new_due_journal]
    return repo


@pytest.fixture
def mock_contact_repo() -> AsyncMock:
    """A contact repository no retarget may touch."""
    return AsyncMock()


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    """A settings repository reporting UTC unless a test configures otherwise."""
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def date_resolver(mock_settings_repo: AsyncMock) -> JournalDateResolver:
    """The real resolver: the future-dated rule is part of what is under test."""
    return JournalDateResolver(mock_settings_repo)


@pytest.fixture
def mock_transaction() -> AsyncMock:
    """A stand-in connection; ``@transactional`` runs unwrapped for a non-real one."""
    return AsyncMock()


@pytest.fixture
def service(
    mock_task_repo: AsyncMock,
    mock_journal_repo: AsyncMock,
    mock_contact_repo: AsyncMock,
    date_resolver: JournalDateResolver,
    mock_event_publisher: AsyncMock,
) -> TaskService:
    """The service under test.

    ``mock_event_publisher`` comes from ``conftest.py``. Retargeting now has its
    own event type and reaches the publisher on every real move, so this double
    records what the operation announced rather than standing in for a
    collaborator that is never touched.
    """
    return TaskService(
        task_repo=mock_task_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=date_resolver,
        event_publisher=mock_event_publisher,
    )


async def retarget(
    service: TaskService,
    transaction: AsyncMock,
    *,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
    due_journal_id: int = NEW_DUE_JOURNAL_ID,
    acknowledge_reopen: bool = False,
    now: datetime.datetime | None = NOW,
) -> Task:
    """Call ``retarget_due_journal`` with the ordinary arguments, overriding as needed."""
    return await service.retarget_due_journal(
        user_id=user_id,
        task_id=task_id,
        due_journal_id=due_journal_id,
        acknowledge_reopen=acknowledge_reopen,
        transaction=transaction,
        now=now,
    )


def retarget_event(publisher: AsyncMock) -> DomainEvent:
    """The anchor-move event from the pair a successful retarget publishes.

    A retarget publishes two events since the phase that gave intermediate links
    their own type: the link it retains, then the anchor move. Most of the tests
    below are about the second, and pick it by type rather than by index so a
    change in the order fails the one test that is *about* the order rather than
    every test in the file at once.
    """
    (event,) = [
        event
        for event in published_events(publisher)
        if event.event_type == "TaskDueJournalRetargeted"
    ]
    return event


def link_event(publisher: AsyncMock) -> DomainEvent:
    """The derived-link event from that same pair."""
    (event,) = [
        event
        for event in published_events(publisher)
        if event.event_type == "TaskJournalLinked"
    ]
    return event


def acknowledgement_for(status: TaskStatus) -> bool:
    """The acknowledgement a task in ``status`` needs to be retargeted at all.

    Only *done* needs one, so parametrised tests that are about something else
    can ask for the right one instead of branching.
    """
    return status is TaskStatus.DONE


@pytest.mark.unit
class TestRetargetingAlwaysLeavesTheTaskNotDone:
    """The specification's outcome rule, for each status a task can start in."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_the_task_lands_not_done(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """Not done stays not done; cancelled is reopened; done is reopened."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        result = await retarget(
            service,
            mock_transaction,
            acknowledge_reopen=acknowledgement_for(current),
        )

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.status == TaskStatus.NOT_DONE
        assert result.status == TaskStatus.NOT_DONE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_the_new_due_journal_is_persisted(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """The whole point of the operation, whatever the task's status."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        result = await retarget(
            service,
            mock_transaction,
            acknowledge_reopen=acknowledgement_for(current),
        )

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.id == TASK_ID
        assert saved.due_journal_id == NEW_DUE_JOURNAL_ID
        assert result.due_journal_id == NEW_DUE_JOURNAL_ID

    @pytest.mark.asyncio
    async def test_the_creating_journal_is_a_legitimate_target(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Invariant 6 holds on a retarget as it does on creation.

        The creating and due journals may be the same journal, provided the
        future-dated rule holds when the due journal is set. Nothing about
        retargeting narrows that, so a task can legitimately be moved back onto
        the journal it arose in — and the journal it is *leaving* still becomes
        an intermediate link.
        """
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, at(TOMORROW))
        ]

        result = await retarget(
            service, mock_transaction, due_journal_id=CREATING_JOURNAL_ID
        )

        assert result.due_journal_id == CREATING_JOURNAL_ID
        assert result.creating_journal_id == CREATING_JOURNAL_ID
        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, OLD_DUE_JOURNAL_ID, USER_ID
        )

    @pytest.mark.asyncio
    async def test_nothing_else_about_the_task_changes(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Retargeting moves the due anchor and the status, and nothing besides.

        The **creating journal** is in this list deliberately: the specification
        sets it once and never changes it, and the service is what enforces that
        (the repository's ``UPDATE`` writes whatever the entity carries).
        """
        await retarget(service, mock_transaction)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.creating_journal_id == CREATING_JOURNAL_ID
        assert saved.text == TASK_TEXT
        assert saved.user_id == USER_ID
        assert saved.created_at == at(YESTERDAY)


@pytest.mark.unit
class TestThePreviousDueJournalIsRetained:
    """The model's one automatic link."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_the_previous_due_journal_becomes_an_intermediate_link(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """So the trail of a repeatedly-deferred task stays on its journals."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        await retarget(
            service,
            mock_transaction,
            acknowledge_reopen=acknowledgement_for(current),
        )

        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, OLD_DUE_JOURNAL_ID, USER_ID
        )

    @pytest.mark.asyncio
    async def test_the_new_due_journal_is_not_linked_as_intermediate(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """It is the due anchor now; a second role would say less, not more."""
        await retarget(service, mock_transaction)

        linked_journal_ids = [
            call.args[1]
            for call in mock_task_repo.add_intermediate_journal.await_args_list
        ]
        assert NEW_DUE_JOURNAL_ID not in linked_journal_ids

    @pytest.mark.asyncio
    async def test_the_link_is_added_even_when_it_is_also_the_creating_journal(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A task created and due in one journal still records that journal.

        ``TaskAnchorRepository.repoint_journal_links`` already documents this
        shape as one a task reaches without any merge — "retargeting keeps the
        previous due journal as an intermediate link" — so this phase must not
        invent a different rule for it.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(
            due_journal_id=CREATING_JOURNAL_ID
        )

        await retarget(service, mock_transaction)

        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, CREATING_JOURNAL_ID, USER_ID
        )

    @pytest.mark.asyncio
    async def test_an_existing_link_is_not_added_twice(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """De-duplication is the repository's idempotent add, not a read-then-add.

        A task retargeted back onto a journal it has already passed through
        reports ``False`` — the link was already there — and the service treats
        that as success rather than asking first, which would open a window for
        a concurrent add between the question and the answer.
        """
        mock_task_repo.add_intermediate_journal.return_value = False

        result = await retarget(service, mock_transaction)

        assert result.due_journal_id == NEW_DUE_JOURNAL_ID
        assert mock_task_repo.add_intermediate_journal.await_count == 1
        mock_task_repo.list_intermediate_journal_ids.assert_not_awaited()


@pytest.mark.unit
class TestReopeningADoneTaskNeedsAcknowledgement:
    """Moving a date is rarely how a user means to undo a completion."""

    @pytest.mark.asyncio
    async def test_without_acknowledgement_it_is_refused(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """And the refusal writes nothing at all — not even the automatic link."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        with pytest.raises(TaskReopenNotAcknowledgedError) as exc_info:
            await retarget(service, mock_transaction)

        assert exc_info.value.task_id == TASK_ID
        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_acknowledgement_it_is_reopened(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The acknowledgement is the whole of what the caller must add."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        result = await retarget(service, mock_transaction, acknowledge_reopen=True)

        assert result.status == TaskStatus.NOT_DONE
        assert result.due_journal_id == NEW_DUE_JOURNAL_ID

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", [TaskStatus.NOT_DONE, TaskStatus.CANCELLED])
    async def test_the_other_statuses_need_no_acknowledgement(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """Reopening a cancelled task *is* the documented way out of cancelled.

        The specification asks the UI to warn before reopening a **completed**
        task, and says nothing of the sort about a cancelled one — retargeting
        is exactly what a user is told to do with it.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        result = await retarget(service, mock_transaction, acknowledge_reopen=False)

        assert result.status == TaskStatus.NOT_DONE

    @pytest.mark.asyncio
    async def test_the_journal_is_judged_before_the_acknowledgement_is_asked_for(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A caller who has just confirmed a reopen must not then be told "past".

        The acknowledgement is a *confirmation*, not a validation, so it belongs
        after everything that can be judged without the user. Both refusals apply
        to this call — the task is done and unacknowledged, and the journal has
        passed — and the one the caller gets is the one they can fix without
        making a decision. Moving the gate above the journal checks flips this
        assertion, which is the whole reason it exists.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = [
            make_journal(NEW_DUE_JOURNAL_ID, at(YESTERDAY))
        ]

        with pytest.raises(TaskDueJournalNotFutureError):
            await retarget(service, mock_transaction, acknowledge_reopen=False)

        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unreachable_journal_is_reported_before_the_acknowledgement(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The same ordering, for the other rule the caller can act on alone."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = []

        with pytest.raises(TaskAnchorJournalNotFoundError):
            await retarget(service, mock_transaction, acknowledge_reopen=False)

        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_refusal_is_distinguishable_from_a_validation_failure(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A surface must be able to offer "reopen anyway", not just "invalid".

        So it is its own type, answers 409 — the body is well formed and the
        journal is real; what it conflicts with is the state the task is in —
        and it is **not** a ``TaskStatusTransitionError``, whose message tells a
        caller to retarget and would be circular here.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        with pytest.raises(TaskReopenNotAcknowledgedError) as exc_info:
            await retarget(service, mock_transaction)

        error = exc_info.value
        assert isinstance(error, TaskDomainError)
        assert not isinstance(error, TaskStatusTransitionError)
        assert error.status_code == 409

    @pytest.mark.asyncio
    async def test_the_refusal_names_the_way_through(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """An agent that cannot see the remedy retries the refused call instead."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        with pytest.raises(TaskReopenNotAcknowledgedError) as exc_info:
            await retarget(service, mock_transaction)

        message = str(exc_info.value)
        assert "done" in message
        assert "acknowledge" in message.lower()


@pytest.mark.unit
class TestTheDueJournalIsRevalidated:
    """Existence and ownership, whatever the task's current status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_an_unreachable_journal_is_refused(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """A journal that does not exist, or is somebody else's, cannot be a target.

        The two are one case because the read is owner-scoped: another user's
        journal is simply not in the result, so the error cannot say which.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = []

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await retarget(
                service,
                mock_transaction,
                acknowledge_reopen=acknowledgement_for(current),
            )

        assert exc_info.value.anchor == "due"
        assert exc_info.value.journal_id == NEW_DUE_JOURNAL_ID
        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_journal_read_is_owner_scoped(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Ownership is enforced by the query, never by a comparison afterwards.

        Both of the retarget's journals go through it, so one it is not allowed
        to see is never even locked.
        """
        await retarget(service, mock_transaction)

        mock_journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, sorted((OLD_DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID))
        )


@pytest.mark.unit
class TestTheFutureDatedRuleIsRevalidated:
    """Invariant 4 applies at *every* moment a due journal is set."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    @pytest.mark.parametrize("day", [YESTERDAY, TODAY])
    async def test_a_journal_that_is_not_in_the_future_is_refused(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
        day: datetime.date,
    ) -> None:
        """Today is not the future either — the rule is *after* today, not *not before*."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = [
            make_journal(NEW_DUE_JOURNAL_ID, at(day))
        ]

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await retarget(
                service,
                mock_transaction,
                acknowledge_reopen=acknowledgement_for(current),
            )

        assert exc_info.value.journal_id == NEW_DUE_JOURNAL_ID
        assert exc_info.value.journal_date == day
        assert exc_info.value.today == TODAY
        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_the_journal_being_left_is_locked_but_never_judged(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """Which is what makes a *lapsed* task resurrectable rather than stuck.

        A lapsed task is one whose due journal has already passed. The journal it
        is leaving **is** loaded now — the lock ordering needs it named before
        the task row is taken — so the property that matters can no longer be
        "it is never read". It is that the future-dated rule is applied to the
        **new** journal alone: here the journal being left is dated in the past
        and comes back from the very same read, and the retarget still succeeds.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = [
            make_journal(OLD_DUE_JOURNAL_ID, at(YESTERDAY), title="Long gone"),
            make_journal(NEW_DUE_JOURNAL_ID, at(TOMORROW)),
        ]

        result = await retarget(
            service,
            mock_transaction,
            acknowledge_reopen=acknowledgement_for(current),
        )

        assert result.due_journal_id == NEW_DUE_JOURNAL_ID
        assert result.status == TaskStatus.NOT_DONE

    @pytest.mark.asyncio
    async def test_the_rule_is_judged_in_the_users_timezone(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A journal still in the future in UTC can already be today in Sydney.

        The same instant is the 5th in UTC and the 6th in Sydney, so a journal
        dated the 6th is future-dated for one user and not for another. The
        timezone is the user's, read through the resolver.
        """
        mock_settings_repo.get_timezone.return_value = SYDNEY

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await retarget(service, mock_transaction, now=NOW_SYDNEY_IS_TOMORROW)

        assert exc_info.value.today == TOMORROW
        mock_settings_repo.get_timezone.assert_awaited_once_with(USER_ID)

    @pytest.mark.asyncio
    async def test_the_supplied_instant_is_used_rather_than_the_clock(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """``now`` is honoured, which is what makes the date cases above deterministic.

        The journal is dated tomorrow relative to the fixture's ``NOW`` and would
        be accepted against it; moved two days on, the same journal is in the
        past. Only the supplied instant can produce that result.

        It must never be bound from client input: a request that could set it
        would make invariant 4 opt-out for any caller.
        """
        later = datetime.datetime(2026, 8, 7, 12, 0, tzinfo=datetime.UTC)

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await retarget(service, mock_transaction, now=later)

        assert exc_info.value.today == datetime.date(2026, 8, 7)
        assert exc_info.value.journal_date == TOMORROW
        assert mock_journal_repo.find_and_lock_by_ids_for_user.await_count == 1


@pytest.mark.unit
class TestUnreachableTasks:
    """Somebody else's task and a nonexistent one are the same answer."""

    @pytest.mark.asyncio
    async def test_unknown_task_is_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """An id that matches nothing raises rather than writing."""
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await retarget(service, mock_transaction)

        assert exc_info.value.task_id == TASK_ID
        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_another_users_task_is_indistinguishable(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Both owner-scoped reads return nothing, so the message cannot leak."""
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await retarget(service, mock_transaction, user_id=OTHER_USER_ID)

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.find_by_id.assert_awaited_once_with(TASK_ID, OTHER_USER_ID)
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_task_deleted_between_the_two_reads_is_still_a_404(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The peek is not authoritative about existence either.

        The task can be deleted while the retarget waits for the journal locks,
        so the locking read is checked for ``None`` in its own right rather than
        trusting what the peek found a moment earlier.
        """
        stored_task(mock_task_repo, peeked=make_task(), locked=None)

        with pytest.raises(TaskNotFoundError):
            await retarget(service, mock_transaction)

        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_read_is_owner_scoped_and_locked(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The row is held while the acknowledgement rule is decided from it.

        Retargeting reads the status, decides whether an acknowledgement was
        needed, and writes that decision back. An unlocked read lets a
        concurrent ``set_status`` mark the task done in between, so the reopen
        happens without the acknowledgement the rule exists to require — the
        same lost *decision* Phase 6 found on ``set_status``.

        The peek that precedes it is owner-scoped too, and takes no lock at all:
        it exists only to name the journals to lock, and every decision below is
        made again from the locked read. See
        :class:`TestTheDecisionsAreMadeFromTheLockedRead`.
        """
        await retarget(service, mock_transaction)

        mock_task_repo.find_by_id_for_update.assert_awaited_once_with(TASK_ID, USER_ID)
        mock_task_repo.find_by_id.assert_awaited_once_with(TASK_ID, USER_ID)


@pytest.mark.unit
class TestRetargetingOntoTheCurrentDueJournal:
    """Asking for the journal a task is already due in is not a retarget."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_is_a_no_op(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """Nothing is written, so ``updated_at`` does not move and no link appears.

        Including *done* without an acknowledgement: nothing is being reopened,
        because nothing is being set. This mirrors the same-status no-op on
        ``set_status`` and keeps invariant 4 a rule about *setting* a due
        journal rather than a rule re-applied on every call.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        result = await retarget(
            service, mock_transaction, due_journal_id=OLD_DUE_JOURNAL_ID
        )

        assert result.status == current
        assert result.due_journal_id == OLD_DUE_JOURNAL_ID
        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reads_no_journal_at_all(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Not even to re-judge its date, which a lapsed task would fail.

        Reading no journal is also **taking no journal lock**: the ordered
        locking read is the retarget's first journal call, so an empty
        ``mock_calls`` says both at once. Asserted on ``mock_calls`` rather than
        on named methods, so a method added to either port later cannot slip
        through.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task()

        await retarget(service, mock_transaction, due_journal_id=OLD_DUE_JOURNAL_ID)

        assert mock_journal_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_the_verdict_comes_from_the_peek_even_when_it_is_stale(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The one decision the unlocked read owns, asserted rather than assumed.

        Everything else a retarget concludes is re-read under the task's row
        lock. This cannot be: deciding the no-op under that lock would mean
        either taking it *before* the journals — the inversion the phase exists
        to remove — or taking journal locks for a call that writes nothing, which
        the criterion above forbids. So when a writer moves the task's due
        journal in the instant between the peek and now, the answer is still
        "nothing to do".

        **That is a snapshot, not a wrong answer.** A no-op writes nothing, so
        what it returns is a read; a merge committing a moment after a *locked*
        no-op had returned would leave the caller holding the same stale journal
        id. The lock narrows the window rather than closing it, and it costs the
        ordering to do so.
        """
        stored_task(
            mock_task_repo,
            peeked=make_task(due_journal_id=NEW_DUE_JOURNAL_ID),
            locked=make_task(due_journal_id=OLD_DUE_JOURNAL_ID),
        )

        result = await retarget(service, mock_transaction)

        assert result.due_journal_id == NEW_DUE_JOURNAL_ID
        mock_task_repo.find_by_id_for_update.assert_not_awaited()
        mock_task_repo.save.assert_not_awaited()
        assert mock_journal_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_takes_no_row_lock_either(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The peek answers it, so a read-only call never takes a writer's lock.

        Nothing is decided and nothing is written, so there is no decision for an
        interleaving to lose — and the retarget now learns the current due
        journal *before* it would have taken the lock anyway.
        """
        await retarget(service, mock_transaction, due_journal_id=OLD_DUE_JOURNAL_ID)

        mock_task_repo.find_by_id.assert_awaited_once_with(TASK_ID, USER_ID)
        mock_task_repo.find_by_id_for_update.assert_not_awaited()


@pytest.mark.unit
class TestTheLockOrderAgreesWithMerge:
    """The journals are taken before the task, ascending, as a merge takes them.

    ``TaskAnchorRepository.repoint_journal_links`` and its caller lock the
    **journals** ``FOR UPDATE`` in ascending id order and only then write the
    **task** rows. Until this phase the retarget did the reverse — task row
    first, journals afterwards through the link insert's and the anchor update's
    foreign keys — so the two deadlocked whenever a merge absorbed the journal a
    task was due in.

    The order is asserted on the calls themselves, across both ports at once,
    because that is the only form a refactor cannot silently invert: an outcome
    assertion passes just as well for the ordering that deadlocks.
    """

    @staticmethod
    def recording(mock_task_repo: AsyncMock, mock_journal_repo: AsyncMock) -> Mock:
        """One parent for both ports, so their two histories become one sequence.

        Two separate mocks record two separate call lists and neither can say
        which happened first, so they are attached to a manager whose
        ``mock_calls`` is the interleaving. It has to be attached **before** the
        call under test: propagation happens when a call is made, not when the
        parent is asked.
        """
        manager = Mock()
        manager.attach_mock(mock_task_repo, "task_repo")
        manager.attach_mock(mock_journal_repo, "journal_repo")
        return manager

    @staticmethod
    def names(manager: Mock) -> list[str]:
        """Every call either port received, named, in order."""
        return [name for name, *_ in manager.mock_calls]

    @pytest.mark.asyncio
    async def test_the_journals_are_locked_before_the_task_row(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The whole point of the phase, stated as a sequence.

        A non-locking peek first — it takes nothing and only names the journals —
        then the ordered locking read on the journal port, then the task's row
        lock. Invert any of the three and this fails.
        """
        manager = self.recording(mock_task_repo, mock_journal_repo)

        await retarget(service, mock_transaction)

        called = self.names(manager)
        assert called.index(
            "journal_repo.find_and_lock_by_ids_for_user"
        ) < called.index("task_repo.find_by_id_for_update")
        assert called.index("task_repo.find_by_id") < called.index(
            "journal_repo.find_and_lock_by_ids_for_user"
        )

    @pytest.mark.asyncio
    async def test_the_writes_happen_after_both_locks(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The two writes take their own foreign-key locks, so they come last.

        ``add_intermediate_journal`` takes ``FOR KEY SHARE`` on the journal the
        task is leaving and ``save`` takes it on the journal it is moving to.
        Both are already held by then, which is what makes them free rather than
        a second, unordered acquisition.
        """
        manager = self.recording(mock_task_repo, mock_journal_repo)

        await retarget(service, mock_transaction)

        called = self.names(manager)
        lock = called.index("journal_repo.find_and_lock_by_ids_for_user")
        assert lock < called.index("task_repo.add_intermediate_journal")
        assert lock < called.index("task_repo.save")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("previous_id", "requested_id"),
        [(22, 33), (33, 22)],
        ids=["previous-is-lower", "previous-is-higher"],
    )
    async def test_the_journal_ids_are_requested_in_ascending_order(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        previous_id: int,
        requested_id: int,
    ) -> None:
        """Ascending id, not "the one being left and then the one being set".

        A merge locks its pair by id, so the retarget has to as well: two
        operations agreeing to take the same rows in *some* fixed order is the
        whole of the guarantee, and the order has to be the same one. The
        parametrisation puts the previous journal on each side of the target so a
        hard-coded ordering passes only half of it.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(
            due_journal_id=previous_id
        )
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = [
            make_journal(requested_id, at(TOMORROW))
        ]

        await retarget(service, mock_transaction, due_journal_id=requested_id)

        mock_journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, sorted((previous_id, requested_id))
        )

    @pytest.mark.asyncio
    async def test_the_non_locking_read_is_not_used_for_the_journals(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """``find_by_ids_for_user`` takes no lock, so it cannot order anything.

        It is still the right read everywhere else in the service; on this path
        substituting it would restore the deadlock while leaving every outcome
        assertion in this file green.
        """
        await retarget(service, mock_transaction)

        mock_journal_repo.find_by_ids_for_user.assert_not_awaited()


@pytest.mark.unit
class TestTheDecisionsAreMadeFromTheLockedRead:
    """The peek names journals. It decides nothing.

    Putting a non-locking read in front of the locking one is only safe if
    nothing is *concluded* from it, because the gap between the two is exactly
    where another writer's commit lands. Every case here makes the two reads
    disagree and asserts the locked one won.
    """

    @pytest.mark.asyncio
    async def test_an_acknowledgement_is_required_for_a_task_done_since_the_peek(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The lost *decision* ITER18-001 Phase 6 closed, re-checked at the peek.

        Somebody marks the task done while the retarget waits for the journal
        locks. Deciding from the peek would reopen a completed task with no
        acknowledgement at all — the rule bypassed by timing rather than by
        request.
        """
        stored_task(
            mock_task_repo,
            peeked=make_task(TaskStatus.NOT_DONE),
            locked=make_task(TaskStatus.DONE),
        )

        with pytest.raises(TaskReopenNotAcknowledgedError):
            await retarget(service, mock_transaction)

        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_acknowledgement_is_required_for_a_task_reopened_since_the_peek(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The converse, so the rule is read from the lock rather than merely stricter.

        A test that only pinned the refusal above would also pass for an
        implementation that demanded an acknowledgement from *both* reads.
        """
        stored_task(
            mock_task_repo,
            peeked=make_task(TaskStatus.DONE),
            locked=make_task(TaskStatus.NOT_DONE),
        )

        result = await retarget(service, mock_transaction)

        assert result.status == TaskStatus.NOT_DONE
        assert result.due_journal_id == NEW_DUE_JOURNAL_ID

    @pytest.mark.asyncio
    async def test_the_status_the_event_reports_comes_from_the_locked_read(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """``previous_status`` is a claim about the row, not about a stale read."""
        stored_task(
            mock_task_repo,
            peeked=make_task(TaskStatus.NOT_DONE),
            locked=make_task(TaskStatus.CANCELLED),
        )

        await retarget(service, mock_transaction)

        changed = retarget_event(mock_event_publisher).event_data["changed_fields"]
        assert changed["status"] == (
            TaskStatus.CANCELLED.value,
            TaskStatus.NOT_DONE.value,
        )

    @pytest.mark.asyncio
    async def test_the_task_written_back_is_the_locked_one(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Not the peek's copy, which would silently undo the other writer's text."""
        peeked = make_task()
        locked = replace(make_task(), text="reworded while we waited")
        stored_task(mock_task_repo, peeked=peeked, locked=locked)

        result = await retarget(service, mock_transaction)

        assert result.text == "reworded while we waited"


@pytest.mark.unit
class TestThePreviousDueJournalIsReVerified:
    """What happens when the peek's answer stops being true.

    The journals have to be named before the task row is locked, and the only
    place they can be named from is a read that takes no lock. So the peek can
    be overtaken — by another retarget, or by the very merge this ordering
    exists to queue behind, which re-points the anchor onto the survivor and
    deletes the journal the peek reported.

    **What re-verification means here is that the peek's answer is discarded**:
    the journal linked and announced comes from the locking read, which is the
    only one that can still be true. It does **not** mean taking the missed
    journal's lock explicitly. That was written and then removed, because it
    bought nothing: the intermediate-link insert's foreign key takes the same
    ``FOR KEY SHARE`` on the same row at the same point in the lock order — after
    the task row — so an extra ordered read only added two round trips to a
    window it could not close. The window is stated on the method instead. It
    needs a *third* concurrent writer, where the ordering this phase fixed needed
    only the pair.
    """

    @pytest.mark.asyncio
    async def test_a_peek_that_still_agrees_locks_once(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The ordinary case pays for none of this."""
        await retarget(service, mock_transaction)

        mock_journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, sorted((OLD_DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID))
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "survivor_id", [44, 11], ids=["survivor-above", "survivor-below"]
    )
    async def test_a_due_journal_that_moved_is_not_locked_a_second_time(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        survivor_id: int,
    ) -> None:
        """One ordered acquisition, whichever side of the target the survivor sits.

        A second one would request a lock the foreign key is about to take
        anyway, at the same point in the order — and when the survivor's id is
        the **lower** of the two it would be a low-after-high acquisition, which
        is the shape of the very inversion this phase removed. The parametrised
        pair is here so that shape cannot be reintroduced by whoever reads the
        ascending case alone and thinks a second call is free.
        """
        stored_task(
            mock_task_repo,
            peeked=make_task(due_journal_id=OLD_DUE_JOURNAL_ID),
            locked=make_task(due_journal_id=survivor_id),
        )

        await retarget(service, mock_transaction)

        assert mock_journal_repo.find_and_lock_by_ids_for_user.await_args_list == [
            call(USER_ID, sorted((OLD_DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID)))
        ]

    @pytest.mark.asyncio
    async def test_the_link_and_the_event_name_the_journal_the_task_really_left(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The trail records where the task was, not where it was a moment before."""
        survivor_id = 44
        stored_task(
            mock_task_repo,
            peeked=make_task(due_journal_id=OLD_DUE_JOURNAL_ID),
            locked=make_task(due_journal_id=survivor_id),
        )

        await retarget(service, mock_transaction)

        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, survivor_id, USER_ID
        )
        changed = retarget_event(mock_event_publisher).event_data["changed_fields"]
        assert changed["due_journal_id"] == (survivor_id, NEW_DUE_JOURNAL_ID)

    @pytest.mark.asyncio
    async def test_a_task_moved_onto_the_requested_journal_becomes_a_no_op(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Somebody else got there first, so there is nothing left to set.

        The same answer the peek would have given had it run a moment later, and
        the same one ``set_status`` gives for a status that is already current.
        """
        stored_task(
            mock_task_repo,
            peeked=make_task(due_journal_id=OLD_DUE_JOURNAL_ID),
            locked=make_task(TaskStatus.DONE, due_journal_id=NEW_DUE_JOURNAL_ID),
        )

        result = await retarget(service, mock_transaction)

        assert result.due_journal_id == NEW_DUE_JOURNAL_ID
        assert result.status == TaskStatus.DONE
        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_intermediate_journal.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()


@pytest.mark.unit
class TestNothingElseIsTouched:
    """The blast radius of a retarget."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_contact_links_are_never_touched(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """Who a task is about does not change because when it is due did."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        await retarget(
            service,
            mock_transaction,
            acknowledge_reopen=acknowledgement_for(current),
        )

        assert mock_contact_repo.mock_calls == []
        mock_task_repo.add_contact.assert_not_awaited()
        mock_task_repo.remove_contact.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_intermediate_link_is_ever_removed(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The trail only grows; a journal a task passed through stays on it.

        Every path is driven, not just the successful one — the refusals and the
        no-op too — because "never removed" is a claim about all of them. A link
        that has become redundant with the new due anchor is left alone as well:
        it is still true (that journal *was* previously due), and the
        specification removes intermediate links only when the user deliberately
        asks, which is a different operation.
        """
        # Success, including the case where the target is already in the trail.
        await retarget(service, mock_transaction)

        # The no-op.
        await retarget(service, mock_transaction, due_journal_id=OLD_DUE_JOURNAL_ID)

        # The acknowledgement refusal.
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)
        with pytest.raises(TaskReopenNotAcknowledgedError):
            await retarget(service, mock_transaction)

        # The journal refusal.
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = []
        with pytest.raises(TaskAnchorJournalNotFoundError):
            await retarget(service, mock_transaction, acknowledge_reopen=True)

        mock_task_repo.remove_intermediate_journal.assert_not_awaited()
        mock_task_repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_journal_that_vanishes_before_the_write_keeps_its_404(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The promised 404 survives, rather than a raw integrity error escaping.

        The window is wider than creation's: the journal-delete guard refuses to
        delete a journal that *already* anchors a task, and the new due journal
        does not anchor this one until the write lands — so a delete between the
        read and the write is permitted, and the foreign key is what stops it.
        The caller must still be told the journal is gone, not handed a 500.
        """
        mock_task_repo.save.side_effect = IntegrityError(
            "UPDATE tasks SET text = $1, status = $2, creating_journal_id = $3, "
            "due_journal_id = $4 WHERE id = $5",
            {},
            Exception(
                'insert or update on table "tasks" violates foreign key '
                'constraint "tasks_due_journal_id_fkey"'
            ),
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await retarget(service, mock_transaction)

        assert exc_info.value.anchor == "due"
        assert exc_info.value.journal_id == NEW_DUE_JOURNAL_ID

    @pytest.mark.asyncio
    async def test_an_unrelated_integrity_error_is_not_disguised(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Only a violation naming an anchor column is translated."""
        mock_task_repo.save.side_effect = IntegrityError(
            "UPDATE tasks SET status = $1 WHERE id = $2",
            {},
            Exception('violates check constraint "ck_tasks_status"'),
        )

        with pytest.raises(IntegrityError):
            await retarget(service, mock_transaction)

    def test_the_creating_journal_cannot_be_set_by_this_operation(self) -> None:
        """Immutability enforced by absence: there is no parameter to pass.

        A test on the saved entity would only show that today's implementation
        happens to carry the value through. What the specification asks for is
        that **no code path can change it**, so the signature is the assertion.
        """
        parameters = inspect.signature(TaskService.retarget_due_journal).parameters

        assert [name for name in parameters if "creating" in name] == []

    def test_creation_remains_the_only_way_to_set_a_creating_journal(self) -> None:
        """And no other service method has grown one either.

        ``create_task_with_trail`` is the second name on this list and is still
        *creation*: it exists so a surface can be handed the new task and its
        (always empty) journal trail from inside one unit of work, and it does
        nothing but delegate to ``create_task``. Widening the set was the honest
        resolution when it first failed here — the invariant is "only creation
        sets a creating journal", not "only one method does". Any **third** name
        appearing, or either of these two ceasing to be a creation path, still
        fails, which is what the assertion is for.
        """
        accepting = {
            name
            for name, member in inspect.getmembers(TaskService, inspect.isfunction)
            if not name.startswith("_")
            and "creating_journal_id" in inspect.signature(member).parameters
        }

        assert accepting == {"create_task", "create_task_with_trail"}


@pytest.mark.unit
class TestARetargetAnnouncesItself:
    """Two events, one for each thing a retarget does.

    The specification lists "due journal retargeted" in the minimum event set,
    and a retarget is the one task operation that does two things at once: it
    moves the due anchor and retains the journal it left. Each is now announced
    by its own type — the link by a ``TaskJournalLinked``, the same type a manual
    attach publishes, and the move by this one — in the order the writes happen.

    **The status change stays inside the retarget payload.** Two events here
    means one per *write*, not one per fact: a reopen is part of the anchor move,
    not a separate thing that happened.
    """

    @pytest.mark.asyncio
    async def test_the_link_and_the_move_are_published_in_that_order(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The phase's third criterion, at the service.

        Asserted as an ordered list of types rather than by looking each one up:
        it has to fail both when an event goes missing and when the two swap, and
        a lookup-by-type assertion cannot see the second.
        """
        await retarget(service, mock_transaction)

        assert [
            event.event_type for event in published_events(mock_event_publisher)
        ] == [
            "TaskJournalLinked",
            "TaskDueJournalRetargeted",
        ]

    @pytest.mark.asyncio
    async def test_no_task_updated_event_rides_along_for_the_status(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """A reopen is part of the move, not a third announcement.

        The pair above is the whole of what a retarget publishes, and a reopen —
        the case with the most facts to report — must not grow it to three.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        await retarget(service, mock_transaction, acknowledge_reopen=True)

        assert len(published_events(mock_event_publisher)) == 2

    @pytest.mark.asyncio
    async def test_the_event_names_the_task_it_is_about(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        await retarget(service, mock_transaction)

        event = retarget_event(mock_event_publisher)
        assert event.aggregate_id == TASK_ID
        assert event.event_data["task_id"] == TASK_ID
        assert event.event_data["user_id"] == USER_ID

    @pytest.mark.asyncio
    async def test_the_payload_carries_the_old_and_new_due_journal(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The phase's first criterion, at the service.

        The old value comes from the locking read — the only place it still
        exists once the row is saved — which is the same reason ``update_task``
        builds its pairs where it does.
        """
        await retarget(service, mock_transaction)

        event = retarget_event(mock_event_publisher)
        change = event.event_data["changed_fields"]["due_journal_id"]
        assert change[0] == OLD_DUE_JOURNAL_ID
        assert change[1] == NEW_DUE_JOURNAL_ID

    @pytest.mark.asyncio
    async def test_the_payload_says_nothing_about_the_retained_link(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The two keys that stood in for the link event are gone.

        They were here only while ``TaskJournalLinked`` did not exist. Leaving
        them would put the same link in front of a reader twice — once as a key
        and once as an event — with nothing saying which to believe if a future
        change made them disagree.
        """
        await retarget(service, mock_transaction)

        payload = retarget_event(mock_event_publisher).event_data
        assert "auto_linked_journal_id" not in payload
        assert "auto_link_created" not in payload

    @pytest.mark.asyncio
    async def test_the_retarget_event_is_published_after_the_anchor_moves(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """So it announces a change that finished, not one that was attempted.

        The save can still fail — a journal deleted between the read and the
        write surfaces as a 404 — and a retarget event published first would have
        announced a move that never happened.

        **The link event is already out at this point, and that is correct.** Its
        own write finished before the save was attempted, and both rows ride the
        connection the failure rolls back, so nothing survives either way. What
        this pins is that the *anchor* event never precedes the anchor write.
        """
        mock_task_repo.save.side_effect = TaskDomainError("the write failed")

        with pytest.raises(TaskDomainError):
            await retarget(service, mock_transaction)

        assert [
            event.event_type for event in published_events(mock_event_publisher)
        ] == ["TaskJournalLinked"]

    @pytest.mark.asyncio
    async def test_the_link_is_written_before_the_anchor_moves(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The ordering this phase hands to the phase that splits the event.

        Both writes are in one transaction, so **nothing observable depends on
        this order today** — which is exactly why it needs a test rather than a
        docstring. The criterion asks for a deterministic order so the trail can
        be rendered coherently, and the phase that gives the intermediate link
        its own event type is told to publish in the order the writes happen. A
        refactor that swapped these two between now and then would silently
        change the contract the next phase was handed, and no other test in this
        repository would notice.

        Asserted on the shared parent mock's call log, which records both calls
        against one timeline; asserting each method's own ``await_args`` would
        say they both happened and nothing about their order.
        """
        await retarget(service, mock_transaction)

        called = [
            name
            for name, *_ in mock_task_repo.mock_calls
            if name in {"add_intermediate_journal", "save"}
        ]
        assert called == ["add_intermediate_journal", "save"]

    @pytest.mark.asyncio
    async def test_the_event_carries_the_callers_transaction(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        await retarget(service, mock_transaction)

        assert retarget_event(mock_event_publisher).transaction is mock_transaction


@pytest.mark.unit
class TestARetargetAnnouncesTheLinkItRetains:
    """The derived link, published as the same type a manual attach publishes.

    The phase's second criterion. Before it, the retained journal travelled as
    two keys on the retarget payload; now it is an event of its own, so a
    consumer treats "this journal became a link" the same way whether a person
    asked for it or a deferral produced it.
    """

    @pytest.mark.asyncio
    async def test_the_link_event_names_the_journal_the_task_left(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The *previous* due journal, not the new one.

        The two are one substitution apart in the source and produce a history
        claiming the task was linked to the journal it just moved *to* — which
        is not a link at all, it is the anchor.
        """
        await retarget(service, mock_transaction)

        event = link_event(mock_event_publisher)
        assert event.aggregate_id == TASK_ID
        assert event.event_data["task_id"] == TASK_ID
        assert event.event_data["user_id"] == USER_ID
        assert event.event_data["journal_id"] == OLD_DUE_JOURNAL_ID

    @pytest.mark.asyncio
    async def test_the_link_records_that_a_retarget_caused_it(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """Half of the criterion's distinction; the actor is the other half."""
        await retarget(service, mock_transaction)

        assert link_event(mock_event_publisher).event_data["origin"] == "retarget"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source", "changed_by"),
        [(Provenance.UI, "ui"), (Provenance.MCP, "mcp")],
    )
    async def test_the_derived_link_is_attributed_to_the_person_who_retargeted(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
        source: Provenance,
        changed_by: str,
    ) -> None:
        """The recorded divergence from the criterion's wording, pinned.

        That criterion says the derived link is separated from a manual one "with
        provenance", which would make this ``system``. It does not, deliberately:
        a retarget is something the **user** did, and the link is a consequence
        of their action rather than a background job. Filing it under ``system``
        would have one user action produce two events disagreeing about who
        performed it, and would tell a person reading their own history that half
        of what they did was not theirs. ``SYSTEM`` is for writes nobody
        triggered — an integration sync — and ``origin`` carries the derivation.

        This is the test that fails if someone later "corrects" it back.
        """
        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=TASK_ID,
            due_journal_id=NEW_DUE_JOURNAL_ID,
            transaction=mock_transaction,
            now=NOW,
            source=source,
            changed_by=changed_by,
        )

        link = link_event(mock_event_publisher)
        assert link.event_data["source"] == source.value
        assert link.event_data["changed_by"] == changed_by

    @pytest.mark.asyncio
    async def test_both_events_of_one_retarget_agree_on_the_actor(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """Stated as an agreement, because that is the property that matters.

        The test above would still pass if the retarget event were the one that
        went wrong. This compares the pair, which is what a reader of the history
        actually sees: two lines, one action, one name against both.
        """
        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=TASK_ID,
            due_journal_id=NEW_DUE_JOURNAL_ID,
            transaction=mock_transaction,
            now=NOW,
            source=Provenance.UI,
            changed_by="ui",
        )

        link = link_event(mock_event_publisher).event_data
        move = retarget_event(mock_event_publisher).event_data
        assert (link["source"], link["changed_by"]) == (
            move["source"],
            move["changed_by"],
        )

    @pytest.mark.asyncio
    async def test_a_link_that_was_already_there_announces_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """Where ``auto_link_created`` went: no row written, no event.

        Reachable whenever a task is retargeted back onto a journal it has
        already passed through — A→B→A→C leaves A a second time while A is still
        linked from the first departure. Publishing here would write "linked
        journal 22" into the user's history twice for one link.
        """
        mock_task_repo.add_intermediate_journal.return_value = False

        await retarget(service, mock_transaction)

        assert [
            event.event_type for event in published_events(mock_event_publisher)
        ] == ["TaskDueJournalRetargeted"]

    @pytest.mark.asyncio
    async def test_the_link_event_is_published_after_the_link_is_written(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """Each event sits behind its own write, which is what fixes the order.

        The publisher is inspected from inside the link write, so this fails if
        the publish is hoisted above it — and with it goes the guarantee that
        the pair reaches a consumer link-first.
        """
        published_at_write: list[int] = []

        async def record(*_args: object) -> bool:
            published_at_write.append(len(mock_event_publisher.mock_calls))
            return True

        mock_task_repo.add_intermediate_journal.side_effect = record

        await retarget(service, mock_transaction)

        assert published_at_write == [0]

    @pytest.mark.asyncio
    async def test_the_link_event_carries_the_callers_transaction(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        await retarget(service, mock_transaction)

        assert link_event(mock_event_publisher).transaction is mock_transaction


@pytest.mark.unit
class TestAReopenIsVisibleInTheEventStream:
    """The phase's third criterion: not only in the task row.

    Retargeting always lands the task not done. When it started somewhere else
    that is a *status change*, and a person reading their own history should see
    it — otherwise a completion silently undone by a date change leaves no trace
    but the date.
    """

    @pytest.mark.asyncio
    async def test_reopening_a_done_task_records_the_status_pair(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        await retarget(service, mock_transaction, acknowledge_reopen=True)

        event = retarget_event(mock_event_publisher)
        change = event.event_data["changed_fields"]["status"]
        assert change[0] == TaskStatus.DONE.value
        assert change[1] == TaskStatus.NOT_DONE.value

    @pytest.mark.asyncio
    async def test_reopening_a_cancelled_task_records_the_status_pair(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The ordinary way out of cancelled, and the same record."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(
            TaskStatus.CANCELLED
        )

        await retarget(service, mock_transaction)

        event = retarget_event(mock_event_publisher)
        change = event.event_data["changed_fields"]["status"]
        assert change[0] == TaskStatus.CANCELLED.value
        assert change[1] == TaskStatus.NOT_DONE.value

    @pytest.mark.asyncio
    async def test_the_move_and_the_reopen_share_one_payload(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """Both facts in one payload, rather than a retarget plus an update.

        The retained link is a second *event* now, but the reopen is not: it is
        part of the anchor move, and splitting it out would announce two things
        where the row changed once.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        await retarget(service, mock_transaction, acknowledge_reopen=True)

        event = retarget_event(mock_event_publisher)
        assert set(event.event_data["changed_fields"]) == {"due_journal_id", "status"}

    @pytest.mark.asyncio
    async def test_a_task_that_was_already_not_done_records_no_status_change(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The common case, and the one a careless implementation gets wrong.

        Forcing the status unconditionally makes "not done → not done" true of
        every deferral; naming it in the payload would put that line in the
        user's history every time they moved a date.
        """
        await retarget(service, mock_transaction)

        event = retarget_event(mock_event_publisher)
        assert list(event.event_data["changed_fields"]) == ["due_journal_id"]


@pytest.mark.unit
class TestARefusedOrEmptyRetargetAnnouncesNothing:
    """No write, no event. Each refusal has its own way of not writing one."""

    @pytest.mark.asyncio
    async def test_retargeting_onto_the_current_due_journal_publishes_nothing(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The no-op, mirroring ``update_task``'s.

        Nothing is set, so ``updated_at`` does not move and no change is
        recorded that did not happen.
        """
        await retarget(service, mock_transaction, due_journal_id=OLD_DUE_JOURNAL_ID)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_an_unknown_task_publishes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError):
            await retarget(service, mock_transaction)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_an_unreachable_due_journal_publishes_nothing(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = []

        with pytest.raises(TaskAnchorJournalNotFoundError):
            await retarget(service, mock_transaction)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_a_journal_that_is_not_in_the_future_publishes_nothing(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        mock_journal_repo.find_and_lock_by_ids_for_user.return_value = [
            make_journal(NEW_DUE_JOURNAL_ID, at(TODAY))
        ]

        with pytest.raises(TaskDueJournalNotFutureError):
            await retarget(service, mock_transaction)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_an_unacknowledged_reopen_publishes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        """The 409 path. A repeated refusal cannot write a second reopen.

        This one is worth its own test rather than folding into the others: the
        acknowledgement is checked *last*, after the journal has been resolved
        and validated, so it is the refusal that gets furthest through the
        method before deciding not to write.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(TaskStatus.DONE)

        with pytest.raises(TaskReopenNotAcknowledgedError):
            await retarget(service, mock_transaction)

        assert published_events(mock_event_publisher) == []


@pytest.mark.unit
class TestProvenanceReachesTheRetargetEvent:
    """Where the retarget came from, so a history can say who moved the date.

    The service defaults to ``SYSTEM``, which is a *silent success*: a caller
    that forgot to say where it was calling from still retargets the task and
    still publishes an event. The only symptom is a person's deferral and an
    assistant's becoming indistinguishable in the user's own history, which is
    why each surface asserts this again for itself.
    """

    @pytest.mark.asyncio
    async def test_it_defaults_to_system(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        await retarget(service, mock_transaction)

        event = retarget_event(mock_event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source", "changed_by"),
        [(Provenance.UI, "ui"), (Provenance.MCP, "mcp")],
    )
    async def test_the_callers_origin_is_recorded(
        self,
        service: TaskService,
        mock_transaction: AsyncMock,
        mock_event_publisher: AsyncMock,
        source: Provenance,
        changed_by: str,
    ) -> None:
        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=TASK_ID,
            due_journal_id=NEW_DUE_JOURNAL_ID,
            transaction=mock_transaction,
            now=NOW,
            source=source,
            changed_by=changed_by,
        )

        event = retarget_event(mock_event_publisher)
        assert event.event_data["source"] == source.value
        assert event.event_data["changed_by"] == changed_by
