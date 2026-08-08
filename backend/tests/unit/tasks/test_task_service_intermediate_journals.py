"""Unit tests for ``TaskService.list_intermediate_journal_ids``.

The method exists so a surface can answer with a task's journal trail without
reaching past the service into a repository. It is deliberately the thinnest
thing in this service, and the tests are about the three properties that make it
safe to be that thin.

**It is a read, so it opens no unit of work.** The transaction rules in
``CLAUDE.md`` put writes inside an explicit unit of work and leave reads outside
one, and this method has nothing to commit. Asserted rather than assumed,
because a ``@transactional`` added here later would take a connection parameter
this signature does not have and would silently commit whatever a caller had
open.

**Ownership is the repository's**, decided by the query rather than by a check
above it — which is what makes another user's task indistinguishable from an
absent one, exactly as every other task read is.

**Order is the repository's too.** The port promises oldest link first, and the
service does not re-sort: a trail whose order came from two places would drift
the moment one of them changed.
"""

import inspect
from unittest.mock import AsyncMock

import pytest
from core_shared.models.tasks import Task, TaskNotFoundError, TaskStatus

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_service import TaskService

USER_ID = "test-user-123"
OTHER_USER_ID = "other-user-456"

TASK_ID = 7


@pytest.fixture
def mock_task_repo() -> AsyncMock:
    """A task repository holding a two-journal trail."""
    repo = AsyncMock()
    repo.list_intermediate_journal_ids.return_value = [11, 22]
    return repo


@pytest.fixture
def service(mock_task_repo: AsyncMock, mock_event_publisher: AsyncMock) -> TaskService:
    """The service under test; nothing but the task repository is reachable.

    ``mock_event_publisher`` comes from ``conftest.py``. A trail read announces
    nothing — it is a read — but the service requires a publisher to construct.
    """
    return TaskService(
        task_repo=mock_task_repo,
        journal_repo=AsyncMock(),
        contact_repo=AsyncMock(),
        date_resolver=JournalDateResolver(AsyncMock()),
        event_publisher=mock_event_publisher,
    )


class TestTheTrailIsReadThroughTheOwnerScopedPort:
    """What the method asks the repository for."""

    async def test_the_ids_come_back_in_the_order_the_repository_gave_them(
        self, service: TaskService
    ) -> None:
        """Oldest link first is the port's promise; the service does not re-sort."""
        ids = await service.list_intermediate_journal_ids(
            user_id=USER_ID, task_id=TASK_ID
        )

        assert ids == [11, 22]

    async def test_the_read_is_scoped_to_the_acting_user(
        self, service: TaskService, mock_task_repo: AsyncMock
    ) -> None:
        """Ownership is decided by the query, as every other task read is."""
        await service.list_intermediate_journal_ids(user_id=USER_ID, task_id=TASK_ID)

        mock_task_repo.list_intermediate_journal_ids.assert_awaited_once_with(
            TASK_ID, USER_ID
        )

    async def test_a_task_with_no_trail_reads_as_an_empty_list(
        self, service: TaskService, mock_task_repo: AsyncMock
    ) -> None:
        """A task that has never been retargeted has passed through nothing.

        Empty is a fact about that task rather than an absence of an answer, so
        it is returned as one instead of ``None``.
        """
        mock_task_repo.list_intermediate_journal_ids.return_value = []

        assert (
            await service.list_intermediate_journal_ids(
                user_id=USER_ID, task_id=TASK_ID
            )
            == []
        )

    async def test_an_unreachable_task_raises_the_domains_not_found(
        self, service: TaskService, mock_task_repo: AsyncMock
    ) -> None:
        """Propagated untouched: another user's task is not found, not empty.

        Swallowing it into ``[]`` would let a surface render somebody else's
        task as one with no trail rather than as one that is not there.
        """
        mock_task_repo.list_intermediate_journal_ids.side_effect = TaskNotFoundError(
            TASK_ID
        )

        with pytest.raises(TaskNotFoundError):
            await service.list_intermediate_journal_ids(
                user_id=OTHER_USER_ID, task_id=TASK_ID
            )


class TestTheTrailIsReadInsideTheWritesUnitOfWork:
    """The four ``*_with_trail`` wrappers, and why they exist.

    Reading the trail *after* the write's unit of work has committed lets a
    concurrent write on the same task land in between, so a response could pair
    an older ``due_journal_id`` and status with a newer set of links — a task
    representation that never existed as one version. Raised by the pull
    request's automated review. ``@transactional`` is re-entrant, so a wrapper
    that calls the write and then the read has both inside one unit of work.
    """

    @pytest.mark.parametrize(
        "method",
        [
            "create_task_with_trail",
            "update_task_with_trail",
            "set_status_with_trail",
            "retarget_due_journal_with_trail",
        ],
    )
    def test_each_wrapper_owns_a_unit_of_work(self, method: str) -> None:
        """Without the decorator the two halves are two transactions again.

        Asserted on the marker ``functools.wraps`` leaves, which is the same
        signal the read below is checked *not* to carry.
        """
        assert hasattr(getattr(TaskService, method), "__wrapped__"), (
            f"{method} must be @transactional, or its read leaves the write's "
            f"unit of work"
        )

    @pytest.mark.parametrize(
        "method",
        [
            "create_task_with_trail",
            "update_task_with_trail",
            "set_status_with_trail",
            "retarget_due_journal_with_trail",
        ],
    )
    def test_each_wrapper_takes_the_transaction_it_joins(self, method: str) -> None:
        parameters = inspect.signature(
            inspect.unwrap(getattr(TaskService, method))
        ).parameters

        assert "transaction" in parameters

    async def test_the_retarget_wrapper_returns_the_task_and_its_trail(
        self, service: TaskService, mock_task_repo: AsyncMock
    ) -> None:
        """Both halves come back together, which is the whole point."""
        task = Task(
            id=TASK_ID,
            user_id=USER_ID,
            text="return Sarah's book",
            creating_journal_id=1,
            due_journal_id=3,
            status=TaskStatus.NOT_DONE,
        )
        mock_task_repo.find_by_id_for_update.return_value = task
        mock_task_repo.save.return_value = task

        retargeted, trail = await service.retarget_due_journal_with_trail(
            user_id=USER_ID,
            task_id=TASK_ID,
            due_journal_id=3,
            transaction=AsyncMock(),
        )

        # Retargeting onto the journal it is already due in is the no-op path,
        # which keeps this test about the *pairing* rather than about Phase 7's
        # rules — those have their own file.
        assert retargeted is task
        assert trail == [11, 22]

    async def test_the_wrapper_reads_the_trail_owner_scoped(
        self, service: TaskService, mock_task_repo: AsyncMock
    ) -> None:
        task = Task(
            id=TASK_ID,
            user_id=USER_ID,
            text="return Sarah's book",
            creating_journal_id=1,
            due_journal_id=3,
            status=TaskStatus.NOT_DONE,
        )
        mock_task_repo.find_by_id_for_update.return_value = task

        await service.retarget_due_journal_with_trail(
            user_id=USER_ID,
            task_id=TASK_ID,
            due_journal_id=3,
            transaction=AsyncMock(),
        )

        mock_task_repo.list_intermediate_journal_ids.assert_awaited_once_with(
            TASK_ID, USER_ID
        )


class TestTheReadOpensNoUnitOfWork:
    """A read commits nothing, so it takes no transaction and owns no boundary."""

    def test_the_signature_takes_no_transaction(self) -> None:
        """The absence *is* the guarantee, so it is asserted rather than described.

        Every writing method on this service takes ``transaction`` and is
        decorated ``@transactional``. This one takes neither, so it cannot
        commit a caller's open work as a side effect of being asked a question.
        """
        parameters = inspect.signature(
            TaskService.list_intermediate_journal_ids
        ).parameters

        assert "transaction" not in parameters
        assert set(parameters) == {"self", "user_id", "task_id"}

    def test_the_method_is_not_transactional(self) -> None:
        """``@transactional`` leaves a marker; a read must not carry one."""
        assert not hasattr(TaskService.list_intermediate_journal_ids, "__wrapped__"), (
            "a read must not be wrapped in a unit of work"
        )
