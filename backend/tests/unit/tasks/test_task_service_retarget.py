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
from unittest.mock import AsyncMock

import pytest
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
from app.core.tasks.services.task_service import TaskService

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
    """A task repository that echoes back whatever it is asked to save."""
    repo = AsyncMock()

    async def save(task: Task) -> Task:
        return task

    repo.save.side_effect = save
    repo.find_by_id_for_update.return_value = make_task()
    repo.add_intermediate_journal.return_value = True
    return repo


@pytest.fixture
def mock_journal_repo(new_due_journal: Journal) -> AsyncMock:
    """A journal repository holding the target journal, owner-scoped like the real one."""
    repo = AsyncMock()
    repo.find_by_ids_for_user.return_value = [new_due_journal]
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
) -> TaskService:
    """The service under test."""
    return TaskService(
        task_repo=mock_task_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=date_resolver,
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
        mock_journal_repo.find_by_ids_for_user.return_value = [
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
        mock_journal_repo.find_by_ids_for_user.return_value = [
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
        mock_journal_repo.find_by_ids_for_user.return_value = []

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
        mock_journal_repo.find_by_ids_for_user.return_value = []

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
        """Ownership is enforced by the query, never by a comparison afterwards."""
        await retarget(service, mock_transaction)

        mock_journal_repo.find_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [NEW_DUE_JOURNAL_ID]
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
        mock_journal_repo.find_by_ids_for_user.return_value = [
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
    async def test_the_journal_being_left_is_never_read(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
    ) -> None:
        """Which is what makes a *lapsed* task resurrectable rather than stuck.

        A lapsed task is one whose due journal has already passed. If the journal
        it is *leaving* were loaded, the future-dated rule would sooner or later
        be applied to it and exactly the tasks a user most needs to resurrect
        would be the ones they could not. Asserted on the ids the journal
        repository is asked for rather than on the outcome, because an outcome
        assertion here would pass for an implementation that reads the old
        journal and then ignores it — and the next person to add a rule would
        find the value already in hand.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        result = await retarget(
            service,
            mock_transaction,
            acknowledge_reopen=acknowledgement_for(current),
        )

        requested = [
            call.args[1]
            for call in mock_journal_repo.find_by_ids_for_user.await_args_list
        ]
        assert requested == [[NEW_DUE_JOURNAL_ID]]
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
        assert mock_journal_repo.find_by_ids_for_user.await_count == 1


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
        """The owner-scoped read returns nothing, so the message cannot leak."""
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await retarget(service, mock_transaction, user_id=OTHER_USER_ID)

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.find_by_id_for_update.assert_awaited_once_with(
            TASK_ID, OTHER_USER_ID
        )
        mock_task_repo.save.assert_not_awaited()

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
        """
        await retarget(service, mock_transaction)

        mock_task_repo.find_by_id_for_update.assert_awaited_once_with(TASK_ID, USER_ID)
        mock_task_repo.find_by_id.assert_not_awaited()


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

        Asserted on ``mock_calls`` rather than on named methods, so a method
        added to either port later cannot slip through.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task()

        await retarget(service, mock_transaction, due_journal_id=OLD_DUE_JOURNAL_ID)

        assert mock_journal_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []


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
        mock_journal_repo.find_by_ids_for_user.return_value = []
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
