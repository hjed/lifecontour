"""Unit tests for the archived-list guard on every ``TaskService`` task write.

An archived list is read-only until it is unarchived, and the specification
extends that to its tasks: "Until unarchived the list and its tasks are
read-only: every list and task write is refused." Phase 6 put the rule on the
entity, as :meth:`~core_shared.models.tasks.TaskList.ensure_writable`; this
phase makes each task write consult it.

What is pinned here, against mocked ports:

- each task write (a flag and icon edit included) refuses a task on an archived list with
  ``TaskListArchivedError``, and writes and publishes nothing first — except
  the delete, whose statement *is* its read, so it refuses after the statement
  and leaves undoing it to the unit of work (proved against a real database in
  ``test_task_service_archived_list_integration.py``);
- a no-op is refused too, as Phase 6 refused a no-op patch of an archived list:
  read-only means not writable, not "writable when nothing changes";
- the list is read with the **share** lock, by the id the task names;
- a task on an active list is written as before;
- a journal-only task never reaches the list repository at all.
"""

import datetime
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import (
    Task,
    TaskIcon,
    TaskList,
    TaskListArchivedError,
    TaskNotFoundError,
    TaskStatus,
)

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.models.repositories import TaskListRepository, TaskRepository
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    CONTACT_ID,
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    INTERMEDIATE_JOURNAL_ID,
    NEW_DUE_JOURNAL_ID,
    TASK_ID,
    TASK_LIST_ID,
    UPDATED_TEXT,
    USER_ID,
    make_list_task,
    make_task,
)

pytestmark = pytest.mark.unit

ARCHIVED_AT = datetime.datetime(2026, 11, 1, 9, 0, tzinfo=datetime.UTC)
# Where a move sends the task: an active list of the user's, so the refusal is
# the task's own archived list rather than the target.
OTHER_TASK_LIST_ID = TASK_LIST_ID + 1
# Far enough ahead that the retarget's future-dated rule holds on any clock.
FUTURE = datetime.datetime(2099, 1, 1, 9, 0, tzinfo=datetime.UTC)


def make_task_list(*, archived: bool, task_list_id: int = TASK_LIST_ID) -> TaskList:
    """The task's list, archived or not."""
    return TaskList(
        id=task_list_id,
        user_id=USER_ID,
        name="Packing",
        position=0,
        archived_at=ARCHIVED_AT if archived else None,
    )


def anchored_list_task() -> Task:
    """A task on the list that also holds both journals.

    Both anchors, so that every write — retargeting and the anchor refusals of
    the intermediate-link methods included — has what it needs to reach the
    point the guard sits at.
    """
    return make_list_task(
        creating_journal_id=CREATING_JOURNAL_ID, due_journal_id=DUE_JOURNAL_ID
    )


def make_journal(journal_id: int, start: datetime.datetime) -> Journal:
    """An instantaneous journal of the acting user's."""
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title="A journal",
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


@pytest.fixture
def task() -> Task:
    """The task every read answers with; a test swaps it for a journal-only one."""
    return anchored_list_task()


@pytest.fixture
def task_repo(task: Task) -> AsyncMock:
    """A task repository holding ``task`` and letting every write through.

    Spec'd on the port, so an ``assert_not_awaited`` on a renamed method fails
    instead of passing vacuously.
    """
    repo = AsyncMock(spec=TaskRepository)

    async def save(saved: Task) -> Task:
        return saved

    repo.find_by_id.return_value = task
    repo.find_by_id_for_update.return_value = task
    # The link writes hold the task with the share lock.
    repo.find_by_id_for_share.return_value = task
    repo.save.side_effect = save
    repo.delete.return_value = task.task_list_id
    repo.add_contacts.return_value = [CONTACT_ID]
    repo.remove_contact.return_value = True
    repo.add_intermediate_journal.return_value = True
    repo.remove_intermediate_journal.return_value = True
    return repo


@pytest.fixture
def task_list_repo() -> AsyncMock:
    """A list repository whose list is archived unless a test says otherwise."""
    repo = AsyncMock(spec=TaskListRepository)
    repo.find_by_id_for_share.return_value = make_task_list(archived=True)
    # A move's target, locked for update; active, so the task's own list refuses.
    repo.find_by_id_for_update.return_value = make_task_list(
        archived=False, task_list_id=OTHER_TASK_LIST_ID
    )
    # The retarget's early refusal reads the list plainly, before any lock.
    repo.find_by_id.return_value = make_task_list(archived=True)
    return repo


def set_list(task_list_repo: AsyncMock, task_list: TaskList | None) -> None:
    """What both of the list repository's reads answer."""
    task_list_repo.find_by_id_for_share.return_value = task_list
    task_list_repo.find_by_id.return_value = task_list


@pytest.fixture
def journal_repo() -> AsyncMock:
    """Journals for the retarget (locked) and the attach (plain read)."""
    repo = AsyncMock()
    journals = {
        journal_id: make_journal(journal_id, FUTURE)
        for journal_id in (DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID, INTERMEDIATE_JOURNAL_ID)
    }

    async def lock(_user_id: str, journal_ids: list[int]) -> list[Journal]:
        return [journals[i] for i in sorted(journal_ids) if i in journals]

    repo.find_and_lock_by_ids_for_user.side_effect = lock
    repo.find_by_ids_for_user.return_value = [
        make_journal(INTERMEDIATE_JOURNAL_ID, FUTURE)
    ]
    return repo


@pytest.fixture
def contact_repo() -> AsyncMock:
    """A contact repository that knows the one contact the link names."""
    repo = AsyncMock()
    repo.find_names_by_ids.return_value = {CONTACT_ID: "Sarah"}
    return repo


@pytest.fixture
def service(
    task_repo: AsyncMock,
    task_list_repo: AsyncMock,
    journal_repo: AsyncMock,
    contact_repo: AsyncMock,
    mock_settings_repo: AsyncMock,
    mock_event_publisher: AsyncMock,
) -> TaskService:
    """The service under test, over mocked ports."""
    return TaskService(
        task_repo=task_repo,
        task_list_repo=task_list_repo,
        journal_repo=journal_repo,
        contact_repo=contact_repo,
        date_resolver=JournalDateResolver(mock_settings_repo),
        event_publisher=mock_event_publisher,
    )


Write = Callable[[TaskService, AsyncMock], Awaitable[object]]


async def _set_status(service: TaskService, tx: AsyncMock) -> object:
    return await service.set_status(
        user_id=USER_ID, task_id=TASK_ID, status=TaskStatus.DONE, transaction=tx
    )


async def _update_text(service: TaskService, tx: AsyncMock) -> object:
    return await service.update_task(
        user_id=USER_ID, task_id=TASK_ID, text=UPDATED_TEXT, transaction=tx
    )


async def _flag_and_icon(service: TaskService, tx: AsyncMock) -> object:
    return await service.update_task(
        user_id=USER_ID,
        task_id=TASK_ID,
        flagged=True,
        icon=TaskIcon.TENT,
        transaction=tx,
    )


async def _delete(service: TaskService, tx: AsyncMock) -> object:
    await service.delete_task(user_id=USER_ID, task_id=TASK_ID, transaction=tx)
    return None


async def _retarget(service: TaskService, tx: AsyncMock) -> object:
    return await service.retarget_due_journal(
        user_id=USER_ID,
        task_id=TASK_ID,
        due_journal_id=NEW_DUE_JOURNAL_ID,
        transaction=tx,
    )


async def _move_to_list(service: TaskService, tx: AsyncMock) -> object:
    return await service.move_to_list(
        user_id=USER_ID,
        task_id=TASK_ID,
        task_list_id=OTHER_TASK_LIST_ID,
        transaction=tx,
    )


async def _remove_from_list(service: TaskService, tx: AsyncMock) -> object:
    return await service.remove_from_list(
        user_id=USER_ID, task_id=TASK_ID, transaction=tx
    )


async def _link_contact(service: TaskService, tx: AsyncMock) -> object:
    return await service.link_contact(
        user_id=USER_ID, task_id=TASK_ID, contact_id=CONTACT_ID, transaction=tx
    )


async def _unlink_contact(service: TaskService, tx: AsyncMock) -> object:
    return await service.unlink_contact(
        user_id=USER_ID, task_id=TASK_ID, contact_id=CONTACT_ID, transaction=tx
    )


async def _attach(service: TaskService, tx: AsyncMock) -> object:
    return await service.attach_intermediate_journal(
        user_id=USER_ID,
        task_id=TASK_ID,
        journal_id=INTERMEDIATE_JOURNAL_ID,
        transaction=tx,
    )


async def _detach(service: TaskService, tx: AsyncMock) -> object:
    return await service.detach_intermediate_journal(
        user_id=USER_ID,
        task_id=TASK_ID,
        journal_id=INTERMEDIATE_JOURNAL_ID,
        transaction=tx,
    )


WRITES: list[tuple[str, Write]] = [
    ("set_status", _set_status),
    ("update_text", _update_text),
    ("flag_and_icon", _flag_and_icon),
    ("delete", _delete),
    ("retarget", _retarget),
    ("move_to_list", _move_to_list),
    ("remove_from_list", _remove_from_list),
    ("link_contact", _link_contact),
    ("unlink_contact", _unlink_contact),
    ("attach_intermediate_journal", _attach),
    ("detach_intermediate_journal", _detach),
]
WRITE_IDS = [name for name, _ in WRITES]
WRITE_CALLS = [write for _, write in WRITES]
# Every write but the retarget, whose refusal comes from a plain read taken
# before its task lock; it is pinned on its own below.
LOCKED_WRITES = [(n, w) for n, w in WRITES if n != "retarget"]
# Every write but the removal, which reads its task again when its list has
# gone and answers for what the list delete left; pinned in
# test_task_service_remove_from_list.py.
GONE_LIST_WRITES = [(n, w) for n, w in WRITES if n != "remove_from_list"]

# Every repository method that changes a row other than the delete, which is
# asserted on its own because it is the one write that runs before the guard.
_ROW_WRITES = (
    "save",
    "add_to_list",
    "remove_from_list",
    "add_contacts",
    "remove_contact",
    "add_intermediate_journal",
    "remove_intermediate_journal",
)


class TestAnArchivedListRefusesEveryTaskWrite:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("write", WRITE_CALLS, ids=WRITE_IDS)
    async def test_the_write_is_refused_naming_the_list(
        self,
        write: Write,
        service: TaskService,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskListArchivedError) as refused:
            await write(service, mock_transaction)

        assert str(TASK_LIST_ID) in refused.value.message
        assert refused.value.status_code == 409

    @pytest.mark.asyncio
    @pytest.mark.parametrize("write", WRITE_CALLS, ids=WRITE_IDS)
    async def test_nothing_is_written_or_published(
        self,
        write: Write,
        service: TaskService,
        task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await write(service, mock_transaction)

        for method in _ROW_WRITES:
            getattr(task_repo, method).assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "write",
        [w for _, w in LOCKED_WRITES],
        ids=[n for n, _ in LOCKED_WRITES],
    )
    async def test_the_list_is_held_with_the_share_lock(
        self,
        write: Write,
        service: TaskService,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The share lock is what keeps an archive from landing between the
        check and the write; a plain read would let it."""
        with pytest.raises(TaskListArchivedError):
            await write(service, mock_transaction)

        task_list_repo.find_by_id_for_share.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID
        )

    @pytest.mark.asyncio
    async def test_the_delete_refuses_on_the_list_its_statement_returned(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """No read precedes the delete, so the list id comes off its own
        ``RETURNING`` — and the refusal after it is undone by the unit of work."""
        task_repo.delete.return_value = 123
        task_list_repo.find_by_id_for_share.return_value = make_task_list(
            archived=True, task_list_id=123
        )

        with pytest.raises(TaskListArchivedError):
            await _delete(service, mock_transaction)

        task_repo.delete.assert_awaited_once_with(TASK_ID, USER_ID)
        task_repo.find_by_id.assert_not_awaited()
        task_repo.find_by_id_for_update.assert_not_awaited()
        task_list_repo.find_by_id_for_share.assert_awaited_once_with(123, USER_ID)


LINK_WRITES = [
    ("link_contact", _link_contact),
    ("unlink_contact", _unlink_contact),
    ("attach_intermediate_journal", _attach),
    ("detach_intermediate_journal", _detach),
]


class TestTheLinkWritesShareLockTheTask:
    """A link write holds the task ``FOR SHARE`` before trusting its list.

    The task can change lists, so a plain read could see the list it is
    leaving while a move commits it onto a list that is then archived. The
    share lock waits for an in-flight move, so the list read after it is the
    task's current one; two link writes on one task share it.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "write",
        [w for _, w in LINK_WRITES],
        ids=[n for n, _ in LINK_WRITES],
    )
    async def test_the_task_is_read_with_the_share_lock_then_its_list(
        self,
        write: Write,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        order: list[str] = []
        task = anchored_list_task()

        async def share_task(*_: object) -> Task:
            order.append("task")
            return task

        async def share_list(*_: object) -> TaskList:
            order.append("list")
            return make_task_list(archived=False)

        task_repo.find_by_id_for_share.side_effect = share_task
        task_list_repo.find_by_id_for_share.side_effect = share_list

        await write(service, mock_transaction)

        task_repo.find_by_id_for_share.assert_awaited_once_with(TASK_ID, USER_ID)
        task_repo.find_by_id.assert_not_awaited()
        task_repo.find_by_id_for_update.assert_not_awaited()
        assert order == ["task", "list"]


class TestTheJournalLinkWritesLockTheJournalFirst:
    """Journal, then task, then list — a journal merge's order.

    A merge locks its journals ``FOR UPDATE`` and then updates the task rows it
    re-anchors. A link write that held the task first and asked for the journal
    second would deadlock against it, so attach and detach lock the journal
    ``FOR KEY SHARE`` before the task.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "write",
        [_attach, _detach],
        ids=["attach_intermediate_journal", "detach_intermediate_journal"],
    )
    async def test_the_journal_is_locked_before_the_task(
        self,
        write: Write,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        order: list[str] = []
        task = anchored_list_task()

        async def lock_journals(_user_id: str, ids: list[int]) -> list[Journal]:
            order.append("journal")
            return [make_journal(i, FUTURE) for i in ids]

        async def share_task(*_: object) -> Task:
            order.append("task")
            return task

        async def share_list(*_: object) -> TaskList:
            order.append("list")
            return make_task_list(archived=False)

        journal_repo.find_and_lock_by_ids_for_user.side_effect = lock_journals
        task_repo.find_by_id_for_share.side_effect = share_task
        task_list_repo.find_by_id_for_share.side_effect = share_list

        await write(service, mock_transaction)

        journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [INTERMEDIATE_JOURNAL_ID]
        )
        assert order == ["journal", "task", "list"]


class TestTheRetargetKeepsTheLockOrder:
    """Journals, then the task, then its list — as every other write.

    The retarget answers its no-op before it locks anything, so its refusal
    comes from a plain read of the list; the share lock that an archive cannot
    slip past is taken after the task row's, not ahead of it.
    """

    @pytest.mark.asyncio
    async def test_an_archived_list_is_refused_before_any_lock(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await _retarget(service, mock_transaction)

        task_list_repo.find_by_id.assert_awaited_once_with(TASK_LIST_ID, USER_ID)
        task_list_repo.find_by_id_for_share.assert_not_awaited()
        journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()
        task_repo.find_by_id_for_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_share_lock_follows_the_task_lock(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        set_list(task_list_repo, make_task_list(archived=False))
        order: list[str] = []
        task = anchored_list_task()

        async def lock_task(*_: object) -> Task:
            order.append("task")
            return task

        async def lock_list(*_: object) -> TaskList:
            order.append("list")
            return make_task_list(archived=False)

        task_repo.find_by_id_for_update.side_effect = lock_task
        task_list_repo.find_by_id_for_share.side_effect = lock_list

        await _retarget(service, mock_transaction)

        assert order == ["task", "list"]

    @pytest.mark.asyncio
    async def test_an_archive_between_the_check_and_the_lock_is_still_refused(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The early read found the list active; the locked one is what decides."""
        task_list_repo.find_by_id.return_value = make_task_list(archived=False)
        task_list_repo.find_by_id_for_share.return_value = make_task_list(archived=True)

        with pytest.raises(TaskListArchivedError):
            await _retarget(service, mock_transaction)

        task_repo.save.assert_not_awaited()
        task_repo.add_intermediate_journal.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()


class TestADueJournalChangeIsRefusedBeforeAnyLock:
    """A due-journal edit peeks first, so its refusal comes before every lock.

    Like the retarget: the journals are locked ahead of the task row, so an
    archived list's task is refused from the plain read — the resend of the
    journal it already has included — and nothing is locked at all.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "due_journal_id",
        [NEW_DUE_JOURNAL_ID, None, DUE_JOURNAL_ID],
        ids=["set", "clear", "resend"],
    )
    async def test_an_archived_list_is_refused_before_any_lock(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        due_journal_id: int | None,
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await service.update_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                due_journal_id=due_journal_id,
                transaction=mock_transaction,
            )

        task_list_repo.find_by_id.assert_awaited_once_with(TASK_LIST_ID, USER_ID)
        journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()
        task_repo.find_by_id_for_update.assert_not_awaited()
        task_repo.save.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_archive_between_the_check_and_the_lock_is_still_refused(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        task_list_repo.find_by_id.return_value = make_task_list(archived=False)
        task_list_repo.find_by_id_for_share.return_value = make_task_list(archived=True)

        with pytest.raises(TaskListArchivedError):
            await service.update_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                due_journal_id=NEW_DUE_JOURNAL_ID,
                transaction=mock_transaction,
            )

        task_repo.save.assert_not_awaited()
        task_repo.add_intermediate_journal.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()


class TestNoOpsAreRefusedToo:
    """Read-only means not writable, as Phase 6 decided for an unchanged patch."""

    @pytest.mark.asyncio
    async def test_setting_the_status_it_already_has(
        self, service: TaskService, mock_transaction: AsyncMock
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await service.set_status(
                user_id=USER_ID,
                task_id=TASK_ID,
                status=TaskStatus.NOT_DONE,
                transaction=mock_transaction,
            )

    @pytest.mark.asyncio
    async def test_resending_the_flag_and_icon_it_already_has(
        self, service: TaskService, task_repo: AsyncMock, mock_transaction: AsyncMock
    ) -> None:
        """An unflagged, icon-less task "set" to unflagged and no icon."""
        with pytest.raises(TaskListArchivedError):
            await service.update_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                flagged=False,
                icon=None,
                transaction=mock_transaction,
            )

        task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retargeting_onto_the_journal_it_is_already_due_in(
        self,
        service: TaskService,
        journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await service.retarget_due_journal(
                user_id=USER_ID,
                task_id=TASK_ID,
                due_journal_id=DUE_JOURNAL_ID,
                transaction=mock_transaction,
            )

        journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_linking_a_contact_that_is_already_linked(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        task_repo.add_contacts.return_value = []

        with pytest.raises(TaskListArchivedError):
            await _link_contact(service, mock_transaction)


class TestWhatIsCheckedFirst:
    @pytest.mark.asyncio
    async def test_an_unknown_contact_is_still_the_answer_for_a_link(
        self,
        service: TaskService,
        contact_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Contacts resolve first, as they always have, so the guard adds no
        new answer to a request that was already wrong."""
        contact_repo.find_names_by_ids.return_value = {}

        with pytest.raises(ContactNotFoundError):
            await _link_contact(service, mock_transaction)

        task_list_repo.find_by_id_for_share.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "write",
        [
            _set_status,
            _retarget,
            _move_to_list,
            _remove_from_list,
            _link_contact,
            _unlink_contact,
            _attach,
            _detach,
        ],
        ids=[
            "set_status",
            "retarget",
            "move",
            "remove",
            "link",
            "unlink",
            "attach",
            "detach",
        ],
    )
    async def test_a_missing_task_is_still_not_found(
        self,
        write: Write,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        task_repo.find_by_id.return_value = None
        task_repo.find_by_id_for_update.return_value = None
        task_repo.find_by_id_for_share.return_value = None

        with pytest.raises(TaskNotFoundError):
            await write(service, mock_transaction)

        task_list_repo.find_by_id_for_share.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "write",
        [w for _, w in GONE_LIST_WRITES],
        ids=[n for n, _ in GONE_LIST_WRITES],
    )
    async def test_a_list_that_cannot_be_read_answers_not_found(
        self,
        write: Write,
        service: TaskService,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Unreachable while the list's foreign key restricts deletes; if it
        ever happens the task is answered as gone rather than as writable."""
        set_list(task_list_repo, None)

        with pytest.raises(TaskNotFoundError):
            await write(service, mock_transaction)


class TestAnActiveListLetsTheWriteThrough:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("write", WRITE_CALLS, ids=WRITE_IDS)
    async def test_the_write_proceeds(
        self,
        write: Write,
        service: TaskService,
        task_list_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        set_list(task_list_repo, make_task_list(archived=False))

        await write(service, mock_transaction)

        task_list_repo.find_by_id_for_share.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID
        )
        mock_event_publisher.publish.assert_awaited()


class TestAJournalOnlyTaskNeverReadsAList:
    @pytest.fixture
    def task(self) -> Task:
        return make_task()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("write", WRITE_CALLS, ids=WRITE_IDS)
    async def test_the_list_repository_is_not_touched(
        self,
        write: Write,
        service: TaskService,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await write(service, mock_transaction)

        task_list_repo.find_by_id_for_share.assert_not_awaited()


async def _reorder(service: TaskService, tx: AsyncMock) -> object:
    return await service.reorder_task(
        user_id=USER_ID, task_id=TASK_ID, after_task_id=None, transaction=tx
    )


async def _arrange(service: TaskService, tx: AsyncMock) -> object:
    return await service.reorder_list_tasks(
        user_id=USER_ID,
        task_list_id=TASK_LIST_ID,
        task_ids=[TASK_ID],
        transaction=tx,
    )


# The reorders publish nothing and refuse a journal-only task outright, so they
# sit outside ``WRITES``, whose active-list and journal-only cases assume an
# event and a write that goes through.
REORDERS: list[tuple[str, Write]] = [
    ("reorder_task", _reorder),
    ("reorder_list_tasks", _arrange),
]


class TestTheReordersAreRefusedToo:
    """Reordering is a write, so an archived list refuses it — a move that would
    change nothing included, since the task is already at the top."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "write", [w for _, w in REORDERS], ids=[n for n, _ in REORDERS]
    )
    async def test_the_reorder_is_refused_under_the_share_lock(
        self,
        write: Write,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await write(service, mock_transaction)

        task_list_repo.find_by_id_for_share.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID
        )
        task_repo.move_within_list.assert_not_awaited()
        task_repo.arrange_open_tasks.assert_not_awaited()


class TestADueDateChangeIsRefusedToo:
    """The due date is one of the task's own fields, so it is guarded with them.

    Driven against an undated list task rather than the suite's anchored one,
    which can never take a due date: the archived answer must come first either
    way, and this proves it is not the invariant answering instead.
    """

    @pytest.fixture
    def task(self) -> Task:
        return make_list_task()

    @pytest.mark.asyncio
    async def test_setting_a_due_date_is_refused(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await service.update_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                due_date=datetime.date(2099, 1, 1),
                transaction=mock_transaction,
            )

        task_repo.save.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_past_date_is_answered_as_archived_first(
        self, service: TaskService, mock_transaction: AsyncMock
    ) -> None:
        with pytest.raises(TaskListArchivedError):
            await service.update_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                due_date=datetime.date(2000, 1, 1),
                transaction=mock_transaction,
            )

    @pytest.mark.asyncio
    async def test_clearing_a_date_it_does_not_have_is_refused(
        self, service: TaskService, task_repo: AsyncMock, mock_transaction: AsyncMock
    ) -> None:
        """A no-op, refused as every no-op on an archived list is."""
        with pytest.raises(TaskListArchivedError):
            await service.update_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                due_date=None,
                transaction=mock_transaction,
            )

        task_repo.save.assert_not_awaited()
