"""Unit tests for reading a list's tasks: its open tasks, and a page of its
closed ones.

The repository answers a list that is not the caller's as an *empty* one, so
the service resolves the list first and turns its absence into the list's 404
— otherwise another user's list would read as a list with nothing on it. These
tests pin that order, the batching (one link read per collection, whatever the
task count), and that the list already resolved seeds the tasks' list refs so
no second list lookup is made.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import Journal
from core_shared.models.tasks import (
    TaskList,
    TaskListNotFoundError,
    TaskListRef,
    TaskPage,
    TaskReadModelPage,
    TaskStatus,
)

from app.core.tasks.services.task_read_service import TaskReadService
from tests.unit.tasks.read_service_doubles import journal_repo_knowing
from tests.unit.tasks.task_doubles import TASK_LIST_ID, USER_ID, make_list_task

pytestmark = pytest.mark.unit

ARCHIVED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def packing_list(*, archived: bool = False) -> TaskList:
    """The list under test, as ``find_by_id`` hands it back."""
    return TaskList(
        id=TASK_LIST_ID,
        user_id=USER_ID,
        name="Packing",
        position=0,
        archived_at=ARCHIVED_AT if archived else None,
    )


@pytest.fixture
def task_repo() -> AsyncMock:
    """A task repository holding no tasks until a test seeds some."""
    repo = AsyncMock()
    repo.find_open_tasks_on_list.return_value = []
    repo.find_closed_tasks_on_list.return_value = TaskPage(tasks=(), total=0)
    repo.list_intermediate_journal_ids_for_tasks.return_value = {}
    repo.list_contact_ids_for_tasks.return_value = {}
    return repo


@pytest.fixture
def journal_repo() -> AsyncMock:
    """A journal repository that knows no journals: list tasks need none."""
    known: dict[int, Journal] = {}
    return journal_repo_knowing(known)


@pytest.fixture(autouse=True)
def task_list_repo(mock_task_list_repo: AsyncMock) -> AsyncMock:
    """The list repository, resolving the list under test for every case."""
    mock_task_list_repo.find_by_id.return_value = packing_list()
    return mock_task_list_repo


def seed_open(task_repo: AsyncMock, count: int) -> None:
    """``count`` open tasks on the list, each with a contact."""
    tasks = [make_list_task(task_id=task_id) for task_id in range(1, count + 1)]
    task_repo.find_open_tasks_on_list.return_value = tasks
    task_repo.list_contact_ids_for_tasks.return_value = {task.id: [] for task in tasks}


class TestTheListIsResolvedFirst:
    """An unknown or another user's list is the list's 404, not an empty list."""

    async def test_open_read_of_an_unknown_list_raises_before_any_task_read(
        self,
        read_service: TaskReadService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
    ) -> None:
        task_list_repo.find_by_id.return_value = None

        with pytest.raises(TaskListNotFoundError):
            await read_service.read_models_on_list(USER_ID, TASK_LIST_ID)

        task_list_repo.find_by_id.assert_awaited_once_with(TASK_LIST_ID, USER_ID)
        task_repo.find_open_tasks_on_list.assert_not_awaited()

    async def test_closed_read_of_an_unknown_list_raises_before_any_task_read(
        self,
        read_service: TaskReadService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
    ) -> None:
        task_list_repo.find_by_id.return_value = None

        with pytest.raises(TaskListNotFoundError):
            await read_service.read_closed_models_on_list(
                USER_ID, TASK_LIST_ID, limit=20, offset=0
            )

        task_list_repo.find_by_id.assert_awaited_once_with(TASK_LIST_ID, USER_ID)
        task_repo.find_closed_tasks_on_list.assert_not_awaited()


class TestOpenTasks:
    """Every open task, in the repository's manual order."""

    async def test_models_keep_the_repository_order(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        task_repo.find_open_tasks_on_list.return_value = [
            make_list_task(task_id=3),
            make_list_task(task_id=1),
            make_list_task(task_id=2),
        ]

        page = await read_service.read_models_on_list(USER_ID, TASK_LIST_ID)

        assert isinstance(page, TaskReadModelPage)
        assert [model.task.id for model in page.models] == [3, 1, 2]
        assert page.total == 3
        task_repo.find_open_tasks_on_list.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID
        )

    async def test_the_resolved_list_seeds_each_tasks_list_ref(
        self,
        read_service: TaskReadService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
    ) -> None:
        """No second list lookup: the list was already read to authorise."""
        seed_open(task_repo, 2)

        page = await read_service.read_models_on_list(USER_ID, TASK_LIST_ID)

        assert {model.task_list for model in page.models} == {
            TaskListRef(id=TASK_LIST_ID, name="Packing", icon=None, archived=False)
        }
        task_list_repo.find_by_ids.assert_not_awaited()

    async def test_an_archived_list_is_readable_and_marked(
        self,
        read_service: TaskReadService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
    ) -> None:
        task_list_repo.find_by_id.return_value = packing_list(archived=True)
        seed_open(task_repo, 1)

        page = await read_service.read_models_on_list(USER_ID, TASK_LIST_ID)

        assert page.models[0].task_list is not None
        assert page.models[0].task_list.archived is True

    @pytest.mark.parametrize("count", [2, 6])
    async def test_links_are_read_once_per_collection(
        self,
        read_service: TaskReadService,
        task_repo: AsyncMock,
        settings_repo: AsyncMock,
        count: int,
    ) -> None:
        """At two tasks and at six, the same number of reads: no N+1."""
        seed_open(task_repo, count)

        await read_service.read_models_on_list(USER_ID, TASK_LIST_ID)

        ids = list(range(1, count + 1))
        task_repo.list_intermediate_journal_ids_for_tasks.assert_awaited_once_with(
            ids, USER_ID
        )
        task_repo.list_contact_ids_for_tasks.assert_awaited_once_with(ids, USER_ID)
        settings_repo.get_timezone.assert_awaited_once()

    async def test_an_empty_list_skips_the_link_reads(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        page = await read_service.read_models_on_list(USER_ID, TASK_LIST_ID)

        assert page == TaskReadModelPage(models=(), total=0)
        task_repo.list_intermediate_journal_ids_for_tasks.assert_not_awaited()
        task_repo.list_contact_ids_for_tasks.assert_not_awaited()


class TestOpenTasksPaged:
    """A ``limit`` cuts the open tasks before they are assembled."""

    async def test_only_the_pages_tasks_reach_the_link_reads(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        seed_open(task_repo, 5)

        page = await read_service.read_models_on_list(
            USER_ID, TASK_LIST_ID, limit=2, offset=2
        )

        assert [model.task.id for model in page.models] == [3, 4]
        assert page.total == 5
        task_repo.list_contact_ids_for_tasks.assert_awaited_once_with([3, 4], USER_ID)

    async def test_an_offset_past_the_end_is_empty_but_keeps_the_total(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        seed_open(task_repo, 3)

        page = await read_service.read_models_on_list(
            USER_ID, TASK_LIST_ID, limit=2, offset=10
        )

        assert page == TaskReadModelPage(models=(), total=3)

    @pytest.mark.parametrize(("limit", "offset"), [(0, 0), (2, -1)])
    async def test_a_bad_limit_or_offset_is_refused(
        self, read_service: TaskReadService, limit: int, offset: int
    ) -> None:
        with pytest.raises(ValueError):
            await read_service.read_models_on_list(
                USER_ID, TASK_LIST_ID, limit=limit, offset=offset
            )


class TestClosedTasks:
    """One page of done and cancelled tasks, with the total across pages."""

    async def test_the_page_and_total_pass_through(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        task_repo.find_closed_tasks_on_list.return_value = TaskPage(
            tasks=(
                make_list_task(TaskStatus.CANCELLED, task_id=9),
                make_list_task(TaskStatus.DONE, task_id=4),
            ),
            total=7,
        )

        page = await read_service.read_closed_models_on_list(
            USER_ID, TASK_LIST_ID, limit=2, offset=4
        )

        task_repo.find_closed_tasks_on_list.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID, limit=2, offset=4
        )
        assert [(m.task.id, m.task.status) for m in page.models] == [
            (9, TaskStatus.CANCELLED),
            (4, TaskStatus.DONE),
        ]
        assert page.total == 7

    async def test_a_page_past_the_end_is_empty_but_keeps_the_total(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        task_repo.find_closed_tasks_on_list.return_value = TaskPage(tasks=(), total=3)

        page = await read_service.read_closed_models_on_list(
            USER_ID, TASK_LIST_ID, limit=20, offset=40
        )

        assert page == TaskReadModelPage(models=(), total=3)
        task_repo.list_contact_ids_for_tasks.assert_not_awaited()


class TestTheReadModelPage:
    def test_it_is_frozen(self) -> None:
        page = TaskReadModelPage(models=(), total=0)

        with pytest.raises(AttributeError):
            page.total = 1  # type: ignore[misc]


class TestTheListWithItsTasks:
    """The one-call read the MCP tool makes: the list resolved once, both
    sections from one ``page`` and ``limit``."""

    async def test_reads_the_list_and_the_timezone_once_for_both_sections(
        self,
        read_service: TaskReadService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        settings_repo: AsyncMock,
    ) -> None:
        seed_open(task_repo, 2)
        task_repo.find_closed_tasks_on_list.return_value = TaskPage(
            tasks=(make_list_task(TaskStatus.DONE, task_id=9),), total=1
        )

        result = await read_service.read_list_with_tasks(
            USER_ID,
            TASK_LIST_ID,
            page=1,
            limit=20,
            page_open_tasks=False,
            include_completed=True,
        )

        assert result.task_list.name == "Packing"
        assert [model.task.id for model in result.open_tasks.models] == [1, 2]
        assert result.completed is not None
        assert [model.task.id for model in result.completed.models] == [9]
        task_list_repo.find_by_id.assert_awaited_once_with(TASK_LIST_ID, USER_ID)
        task_list_repo.find_by_ids.assert_not_awaited()
        settings_repo.get_timezone.assert_awaited_once()

    async def test_the_page_pages_completed_and_leaves_open_whole_by_default(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        seed_open(task_repo, 5)

        result = await read_service.read_list_with_tasks(
            USER_ID,
            TASK_LIST_ID,
            page=3,
            limit=2,
            page_open_tasks=False,
            include_completed=True,
        )

        task_repo.find_closed_tasks_on_list.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID, limit=2, offset=4
        )
        assert len(result.open_tasks.models) == 5

    async def test_page_open_tasks_pages_the_open_tasks_with_the_same_page(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        seed_open(task_repo, 5)

        result = await read_service.read_list_with_tasks(
            USER_ID,
            TASK_LIST_ID,
            page=2,
            limit=2,
            page_open_tasks=True,
            include_completed=True,
        )

        assert [model.task.id for model in result.open_tasks.models] == [3, 4]
        assert result.open_tasks.total == 5

    async def test_without_completed_tasks_no_closed_read_is_made(
        self, read_service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        result = await read_service.read_list_with_tasks(
            USER_ID,
            TASK_LIST_ID,
            page=1,
            limit=20,
            page_open_tasks=False,
            include_completed=False,
        )

        assert result.completed is None
        task_repo.find_closed_tasks_on_list.assert_not_awaited()

    async def test_an_unknown_list_raises_before_any_task_read(
        self,
        read_service: TaskReadService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
    ) -> None:
        task_list_repo.find_by_id.return_value = None

        with pytest.raises(TaskListNotFoundError):
            await read_service.read_list_with_tasks(
                USER_ID,
                TASK_LIST_ID,
                page=1,
                limit=20,
                page_open_tasks=False,
                include_completed=True,
            )

        task_repo.find_open_tasks_on_list.assert_not_awaited()
        task_repo.find_closed_tasks_on_list.assert_not_awaited()

    @pytest.mark.parametrize(("page", "limit"), [(0, 20), (1, 0)])
    async def test_a_bad_page_or_limit_is_refused(
        self, read_service: TaskReadService, page: int, limit: int
    ) -> None:
        with pytest.raises(ValueError):
            await read_service.read_list_with_tasks(
                USER_ID,
                TASK_LIST_ID,
                page=page,
                limit=limit,
                page_open_tasks=False,
                include_completed=True,
            )
