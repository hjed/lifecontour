"""Unit tests for creating a task on a list.

A task on a list may have no journal at all (spec *Core invariants* 1 and 5),
and it may carry a due date, which must be today or later in the user's
timezone. What is pinned here, against mocked ports:

- the task is saved with the list and the date and no journals, and the
  ``TaskCreated`` it publishes carries the list and the date;
- the list is read with the **update** lock, never the share lock: the insert
  then computes the bottom of that list, and taking share first and update
  second would be a lock upgrade two concurrent creates deadlock on;
- the refusals come in a fixed order: entity rules, an unknown list,
  an unknown contact, an archived list, then a past due date — and a refused
  create writes and publishes nothing.

``JournalDateResolver`` is the real collaborator over a mocked settings
repository, because the timezone rule is part of the behaviour under test. The
date cases inject ``now`` rather than reading the clock.
"""

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    Task,
    TaskDueDateInPastError,
    TaskList,
    TaskListArchivedError,
    TaskListNotFoundError,
    TaskStatus,
    TaskValidationError,
)

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.models.events import TaskCreated
from app.core.tasks.models.repositories import TaskListRepository
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    CONTACT_ID,
    ORIGINAL_TEXT,
    OTHER_CONTACT_ID,
    TASK_LIST_ID,
    USER_ID,
    published_events,
)

pytestmark = pytest.mark.unit

SAVED_TASK_ID = 501
SYDNEY = "Australia/Sydney"

# 2026-08-05 14:30 UTC is already 2026-08-06 00:30 in Sydney, so "today" depends
# on the zone: the instant a UTC-today rule would get wrong.
NOW = datetime.datetime(2026, 8, 5, 14, 30, tzinfo=datetime.UTC)
UTC_TODAY = datetime.date(2026, 8, 5)
SYDNEY_TODAY = datetime.date(2026, 8, 6)


def active_list() -> TaskList:
    """The acting user's list, not archived."""
    return TaskList(id=TASK_LIST_ID, user_id=USER_ID, name="Packing", position=0)


def archived_list() -> TaskList:
    """The acting user's list, archived and so read-only."""
    return TaskList(
        id=TASK_LIST_ID,
        user_id=USER_ID,
        name="Packing",
        position=0,
        archived_at=NOW,
    )


@pytest.fixture
def mock_task_repo() -> AsyncMock:
    """A task repository whose save assigns an id and the bottom position."""
    repo = AsyncMock()

    async def save(task: Task) -> Task:
        return Task(
            id=SAVED_TASK_ID,
            user_id=task.user_id,
            text=task.text,
            task_list_id=task.task_list_id,
            position=3,
            due_date=task.due_date,
            creating_journal_id=task.creating_journal_id,
            due_journal_id=task.due_journal_id,
            status=task.status,
        )

    repo.save.side_effect = save

    async def add_contacts(
        _task_id: int, contact_ids: list[int], _user_id: str
    ) -> list[int]:
        return list(contact_ids)

    repo.add_contacts.side_effect = add_contacts
    return repo


@pytest.fixture
def mock_task_list_repo() -> AsyncMock:
    """A list repository holding the acting user's active list."""
    repo = AsyncMock(spec=TaskListRepository)
    repo.find_by_id_for_update.return_value = active_list()
    return repo


@pytest.fixture
def mock_journal_repo() -> AsyncMock:
    """A journal repository a create on a list never touches."""
    return AsyncMock()


@pytest.fixture
def mock_contact_repo() -> AsyncMock:
    """A contact repository that knows the two shared contacts."""
    repo = AsyncMock()
    repo.find_names_by_ids.return_value = {
        CONTACT_ID: "Sarah",
        OTHER_CONTACT_ID: "Sam",
    }
    return repo


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    """A settings repository reporting UTC unless a test says otherwise."""
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def mock_event_publisher() -> AsyncMock:
    """The outbox publisher, recording what the create announced."""
    return AsyncMock()


@pytest.fixture
def mock_transaction() -> AsyncMock:
    """A stand-in connection; ``@transactional`` runs unwrapped for a non-real one."""
    return AsyncMock()


@pytest.fixture
def service(
    mock_task_repo: AsyncMock,
    mock_task_list_repo: AsyncMock,
    mock_journal_repo: AsyncMock,
    mock_contact_repo: AsyncMock,
    mock_settings_repo: AsyncMock,
    mock_event_publisher: AsyncMock,
) -> TaskService:
    """The service under test."""
    return TaskService(
        task_repo=mock_task_repo,
        task_list_repo=mock_task_list_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=JournalDateResolver(mock_settings_repo),
        event_publisher=mock_event_publisher,
    )


async def create_on_list(
    service: TaskService,
    transaction: AsyncMock,
    *,
    text: str = ORIGINAL_TEXT,
    due_date: datetime.date | None = None,
    contact_ids: list[int] | None = None,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
) -> Task:
    """Call ``create_list_task`` with the ordinary arguments, overriding as needed."""
    return await service.create_list_task(
        user_id=USER_ID,
        task_list_id=TASK_LIST_ID,
        text=text,
        due_date=due_date,
        contact_ids=contact_ids,
        transaction=transaction,
        now=NOW,
        source=source,
        changed_by=changed_by,
    )


def assert_nothing_written(task_repo: AsyncMock, event_publisher: AsyncMock) -> None:
    """A refused create leaves no task, no links and no event behind."""
    task_repo.save.assert_not_awaited()
    task_repo.add_contacts.assert_not_awaited()
    event_publisher.publish.assert_not_awaited()


class TestCreatingAnUndatedTask:
    """The plainest create: a list, some text, nothing else."""

    async def test_saves_a_task_on_the_list_with_no_journal(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await create_on_list(service, mock_transaction)

        saved: Task = mock_task_repo.save.await_args.args[0]
        assert saved.id is None
        assert saved.user_id == USER_ID
        assert saved.text == ORIGINAL_TEXT
        assert saved.task_list_id == TASK_LIST_ID
        # The repository places it: the service never guesses the bottom.
        assert saved.position is None
        assert saved.due_date is None
        assert saved.creating_journal_id is None
        assert saved.due_journal_id is None
        assert saved.status is TaskStatus.NOT_DONE

    async def test_returns_the_persisted_task(
        self, service: TaskService, mock_transaction: AsyncMock
    ) -> None:
        created = await create_on_list(service, mock_transaction)

        assert created.id == SAVED_TASK_ID
        assert created.position == 3

    async def test_publishes_one_created_event_carrying_the_list(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await create_on_list(
            service, mock_transaction, source=Provenance.MCP, changed_by="mcp"
        )

        [event] = published_events(mock_event_publisher)
        assert isinstance(event, TaskCreated)
        assert event.aggregate_id == SAVED_TASK_ID
        assert event.event_data["task_list_id"] == TASK_LIST_ID
        assert event.event_data["due_date"] is None
        assert event.event_data["creating_journal_id"] is None
        assert event.event_data["due_journal_id"] is None
        assert event.event_data["contact_ids"] == []
        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"
        assert event.transaction is mock_transaction

    async def test_reads_the_list_with_the_update_lock_never_the_share_lock(
        self,
        service: TaskService,
        mock_task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The insert computes the bottom under this same lock.

        Share first and update second would be a lock upgrade, and two creates
        on one list holding share would each wait for the other to let go.
        """
        await create_on_list(service, mock_transaction)

        mock_task_list_repo.find_by_id_for_update.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID
        )
        mock_task_list_repo.find_by_id_for_share.assert_not_awaited()

    async def test_never_reads_a_journal(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await create_on_list(service, mock_transaction)

        assert mock_journal_repo.mock_calls == []


class TestCreatingWithADueDate:
    """A due date must be today or later, in the user's own timezone."""

    async def test_today_in_the_users_timezone_is_accepted(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_settings_repo.get_timezone.return_value = SYDNEY

        await create_on_list(service, mock_transaction, due_date=SYDNEY_TODAY)

        saved: Task = mock_task_repo.save.await_args.args[0]
        assert saved.due_date == SYDNEY_TODAY
        [event] = published_events(mock_event_publisher)
        assert event.event_data["due_date"] == SYDNEY_TODAY.isoformat()

    async def test_yesterday_in_the_users_timezone_is_refused(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """UTC's today is already yesterday in Sydney at this instant."""
        mock_settings_repo.get_timezone.return_value = SYDNEY

        with pytest.raises(TaskDueDateInPastError) as raised:
            await create_on_list(service, mock_transaction, due_date=UTC_TODAY)

        assert raised.value.due_date == UTC_TODAY
        assert raised.value.today == SYDNEY_TODAY
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    async def test_an_undated_task_does_not_need_a_timezone(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await create_on_list(service, mock_transaction)

        mock_settings_repo.get_timezone.assert_not_awaited()


class TestRefusals:
    """Each refusal writes nothing, and they come in a fixed order."""

    async def test_blank_text_is_refused_before_any_read(
        self,
        service: TaskService,
        mock_task_list_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskValidationError) as raised:
            await create_on_list(service, mock_transaction, text="   ")

        assert raised.value.field == "text"
        mock_task_list_repo.find_by_id_for_update.assert_not_awaited()
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    async def test_a_list_that_is_not_found_is_refused(
        self,
        service: TaskService,
        mock_task_list_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Missing and another user's are one answer: the read is owner-scoped."""
        mock_task_list_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskListNotFoundError) as raised:
            await create_on_list(service, mock_transaction)

        assert raised.value.task_list_id == TASK_LIST_ID
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    async def test_an_unknown_contact_is_refused(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(ContactNotFoundError):
            await create_on_list(service, mock_transaction, contact_ids=[12345])

        assert_nothing_written(mock_task_repo, mock_event_publisher)

    async def test_an_unknown_contact_is_reported_before_the_archived_list(
        self,
        service: TaskService,
        mock_task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_list_repo.find_by_id_for_update.return_value = archived_list()

        with pytest.raises(ContactNotFoundError):
            await create_on_list(service, mock_transaction, contact_ids=[12345])

    async def test_an_archived_list_is_refused(
        self,
        service: TaskService,
        mock_task_list_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_list_repo.find_by_id_for_update.return_value = archived_list()

        with pytest.raises(TaskListArchivedError):
            await create_on_list(service, mock_transaction)

        assert_nothing_written(mock_task_repo, mock_event_publisher)

    async def test_an_archived_list_is_reported_before_a_past_due_date(
        self,
        service: TaskService,
        mock_task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Correcting the date would not make the create succeed; unarchiving would."""
        mock_task_list_repo.find_by_id_for_update.return_value = archived_list()

        with pytest.raises(TaskListArchivedError):
            await create_on_list(
                service,
                mock_transaction,
                due_date=UTC_TODAY - datetime.timedelta(days=1),
            )


class TestContacts:
    """The people a task on a list is created with."""

    async def test_links_the_named_contacts_once_each(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await create_on_list(
            service,
            mock_transaction,
            contact_ids=[CONTACT_ID, OTHER_CONTACT_ID, CONTACT_ID],
        )

        mock_task_repo.add_contacts.assert_awaited_once_with(
            SAVED_TASK_ID, [CONTACT_ID, OTHER_CONTACT_ID], USER_ID
        )

    async def test_the_event_names_the_contacts_actually_linked(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        async def add_contacts(
            _task_id: int, _contact_ids: list[int], _user_id: str
        ) -> list[int]:
            return [OTHER_CONTACT_ID]

        mock_task_repo.add_contacts.side_effect = add_contacts

        await create_on_list(
            service, mock_transaction, contact_ids=[CONTACT_ID, OTHER_CONTACT_ID]
        )

        [event] = published_events(mock_event_publisher)
        assert event.event_data["contact_ids"] == [OTHER_CONTACT_ID]
