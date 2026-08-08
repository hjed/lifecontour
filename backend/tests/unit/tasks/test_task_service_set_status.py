"""Unit tests for ``TaskService.set_status``.

The transition matrix itself is pinned in ``test_task_status_transitions.py``.
What is under test here is the service's part of the specification's lifecycle
rules:

- marking a task done or cancelled **requires no journal and creates no journal
  link** — so no journal repository call and no link write happens on any path;
- a task that is not the acting user's is indistinguishable from one that does
  not exist, because the repository read is owner-scoped;
- a refused transition writes nothing at all;
- a call that asks for the status the task already has is a no-op rather than a
  write, so nothing churns ``updated_at`` and no status-change event exists for
  the history projection to pick up later.

Repositories are mocked: none of this needs a database, and the transitions
matter more than the SQL, which the integration test covers.

The doubles live in ``conftest.py`` and ``task_doubles.py`` beside this file:
Phase 9 added two more member-route operations that start from exactly this
position, so the setup moved rather than being copied a third time.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.tasks import (
    Task,
    TaskNotFoundError,
    TaskStatus,
    TaskStatusTransitionError,
)

from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    ORIGINAL_TEXT,
    OTHER_USER_ID,
    TASK_ID,
    USER_ID,
    make_task,
)


async def set_status(
    service: TaskService,
    transaction: AsyncMock,
    status: TaskStatus,
    *,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
) -> Task:
    """Call ``set_status`` with the ordinary arguments, overriding as needed."""
    return await service.set_status(
        user_id=user_id,
        task_id=task_id,
        status=status,
        transaction=transaction,
    )


@pytest.mark.unit
class TestAllowedTransitions:
    """The seven open cells, through the service."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TaskStatus.NOT_DONE, TaskStatus.DONE),
            (TaskStatus.NOT_DONE, TaskStatus.CANCELLED),
            (TaskStatus.DONE, TaskStatus.NOT_DONE),
            (TaskStatus.DONE, TaskStatus.CANCELLED),
        ],
    )
    async def test_persists_the_new_status(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        current: TaskStatus,
        target: TaskStatus,
    ) -> None:
        """Every permitted change is written and returned."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(current)

        result = await set_status(service, mock_transaction, target)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.id == TASK_ID
        assert saved.status == target
        assert result.status == target

    @pytest.mark.asyncio
    async def test_reads_the_task_owner_scoped_and_locked(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Ownership is enforced by the query, and the row is held while deciding.

        The locking read is asserted here rather than through a concurrent
        integration test because *which read is used* is the whole of the fix:
        this method decides from the status it read and writes that decision
        back, so an unlocked read lets two overlapping calls both pass the
        matrix and the later one win. A refactor that "simplified" this back to
        the plain read would reopen that hole silently, and the race itself is
        also covered end-to-end in
        ``test_task_service_set_status_integration.py``.
        """
        await set_status(service, mock_transaction, TaskStatus.DONE)

        mock_task_repo.find_by_id_for_update.assert_awaited_once_with(TASK_ID, USER_ID)
        mock_task_repo.find_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_leaves_the_anchors_and_text_alone(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A status change changes the status and nothing else."""
        await set_status(service, mock_transaction, TaskStatus.DONE)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.creating_journal_id == CREATING_JOURNAL_ID
        assert saved.due_journal_id == DUE_JOURNAL_ID
        assert saved.text == ORIGINAL_TEXT
        assert saved.user_id == USER_ID


@pytest.mark.unit
class TestNoJournalIsInvolved:
    """Marking done or cancelled requires no journal and creates no link."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target", [TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.NOT_DONE]
    )
    async def test_creates_no_journal_link(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        target: TaskStatus,
    ) -> None:
        """No intermediate journal is attached by a status change."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(
            TaskStatus.DONE if target is TaskStatus.NOT_DONE else TaskStatus.NOT_DONE
        )

        await set_status(service, mock_transaction, target)

        mock_task_repo.add_intermediate_journal.assert_not_awaited()
        mock_task_repo.add_contacts.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_the_journal_repository_is_never_touched(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
        target: TaskStatus,
    ) -> None:
        """Not even the due journal is loaded: no journal is needed to say done.

        This is what keeps a *lapsed* task completable. Re-reading the due
        journal here would invite a future-dated re-check on a rule the
        specification applies only when a due journal is **set** — and that
        would make exactly the tasks a user most needs to close the ones they
        cannot.

        Asserted on ``mock_calls`` rather than on named methods: naming them
        would pass for any method somebody adds to the port later, which is the
        opposite of what "no journal is involved" is supposed to guarantee. The
        settings repository goes with it, because the timezone is only ever
        needed to judge a journal's date.
        """
        await set_status(service, mock_transaction, target)

        assert mock_journal_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []


@pytest.mark.unit
class TestRefusedTransitions:
    """The two closed cells write nothing."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", [TaskStatus.NOT_DONE, TaskStatus.DONE])
    async def test_refuses_leaving_cancelled(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        target: TaskStatus,
    ) -> None:
        """A cancelled task is reopened by retargeting, never by a status call."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(
            TaskStatus.CANCELLED
        )

        with pytest.raises(TaskStatusTransitionError) as exc_info:
            await set_status(service, mock_transaction, target)

        assert exc_info.value.current_status == TaskStatus.CANCELLED
        assert exc_info.value.target_status == target
        mock_task_repo.save.assert_not_awaited()


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
            await set_status(service, mock_transaction, TaskStatus.DONE)

        assert exc_info.value.task_id == TASK_ID
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_another_users_task_is_indistinguishable(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The owner-scoped read returns nothing, so the message cannot leak.

        The repository is asked for the task *as the other user*, which is the
        only way the service ever learns of ownership — it never compares a
        ``user_id`` itself, so there is no branch that could say more.
        """
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await set_status(
                service, mock_transaction, TaskStatus.DONE, user_id=OTHER_USER_ID
            )

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.find_by_id_for_update.assert_awaited_once_with(
            TASK_ID, OTHER_USER_ID
        )
        mock_task_repo.save.assert_not_awaited()


@pytest.mark.unit
class TestSameStatus:
    """Asking for the status a task already has is not a write."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_is_a_no_op(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus,
    ) -> None:
        """Including cancelled → cancelled, which is not a reopening."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(status)

        result = await set_status(service, mock_transaction, status)

        assert result.status == status
        mock_task_repo.save.assert_not_awaited()


@pytest.mark.unit
class TestSetStatusIsTheUpdatePath:
    """Phase 9 made ``set_status`` a delegation, and it must stay one.

    A status change can arrive on its own (this method, and the MCP tool behind
    it) or beside a text edit in one ``PATCH``. Two implementations of the
    transition matrix would be two places for it to drift, and only one of them
    would be the one a given caller hit — so there is one, and this asserts the
    delegation rather than trusting the two to be kept in step by hand.

    Every other test in this file then covers both paths at once, which is why
    the delegation is worth pinning rather than treating as an implementation
    detail.
    """

    @pytest.mark.asyncio
    async def test_the_status_only_path_reaches_the_same_code(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The text is left alone, which is what "status only" has to mean."""
        result = await set_status(service, mock_transaction, TaskStatus.DONE)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.text == ORIGINAL_TEXT
        assert result.text == ORIGINAL_TEXT
        assert result.status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_it_produces_the_same_result_as_the_combined_update(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Same task, same target status, same answer — through either entry point."""
        through_set_status = await set_status(
            service, mock_transaction, TaskStatus.CANCELLED
        )

        mock_task_repo.find_by_id_for_update.return_value = make_task()
        through_update = await service.update_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            status=TaskStatus.CANCELLED,
            transaction=mock_transaction,
        )

        assert through_set_status == through_update
