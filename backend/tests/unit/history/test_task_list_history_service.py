"""Unit tests for TaskListHistoryService: whose history a list's is.

A list is authorised the way a task is (see ``test_task_history_service.py``),
for the same reason: lists are going to be hard-deleted, and the
``__deleted__`` row that leaves behind has to stay readable by its owner and
by nobody else. So the owner stamped on the history rows answers first, and
the live list row is only the fallback for a list whose events have not been
projected yet.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskList, TaskListNotFoundError

from app.core.history.models import FieldHistoryEntry
from app.core.history.services.task_list_history_service import (
    TaskListHistoryService,
)
from tests.unit.history.history_fakes import FakeHistoryRepo

OWNER = "u1"
INTRUDER = "u2"
LIST_ID = 7


def _entry(field_name: str) -> FieldHistoryEntry:
    return FieldHistoryEntry(
        entity_type="task_list",
        entity_id=LIST_ID,
        field_name=field_name,
        old_value=None,
        new_value="Packing",
        changed_by="ui",
        source=Provenance.UI,
        event_id=f"evt-{field_name}",
        id=1,
        created_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
        user_id=OWNER,
    )


class FakeTaskListRepo:
    """Owner-scoped like the real one: another user's list is not found."""

    def __init__(self, task_list: TaskList | None) -> None:
        self._task_list = task_list
        self.calls: list[tuple[int, str]] = []

    async def find_by_id(self, task_list_id: int, user_id: str) -> TaskList | None:
        self.calls.append((task_list_id, user_id))
        if self._task_list is None or self._task_list.user_id != user_id:
            return None
        return self._task_list


def _live_list() -> TaskList:
    return TaskList(id=LIST_ID, user_id=OWNER, name="Packing", position=0)


def _service(
    history: FakeHistoryRepo, lists: FakeTaskListRepo
) -> TaskListHistoryService:
    return TaskListHistoryService(
        history_repo=history,  # type: ignore[arg-type]
        task_list_repo=lists,  # type: ignore[arg-type]
    )


class TestTheHistoryRowsAnswerFirst:
    async def test_the_owner_reads_a_list_whose_row_is_gone(self) -> None:
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__created__")])

        entries = await _service(history, FakeTaskListRepo(None)).get_task_list_history(
            task_list_id=LIST_ID, user_id=OWNER
        )

        assert [e.field_name for e in entries] == ["__created__"]

    async def test_another_user_is_refused_and_nothing_is_read(self) -> None:
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__created__")])

        with pytest.raises(TaskListNotFoundError):
            await _service(history, FakeTaskListRepo(None)).get_task_list_history(
                task_list_id=LIST_ID, user_id=INTRUDER
            )

        assert history.aggregate_calls == []

    async def test_the_list_row_is_not_consulted_when_the_rows_answer(self) -> None:
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__created__")])
        lists = FakeTaskListRepo(_live_list())

        await _service(history, lists).get_task_list_history(
            task_list_id=LIST_ID, user_id=OWNER
        )

        assert lists.calls == []


class TestTheListRowIsTheFallback:
    async def test_an_unprojected_list_reads_empty(self) -> None:
        history = FakeHistoryRepo(owner=None)
        lists = FakeTaskListRepo(_live_list())

        entries = await _service(history, lists).get_task_list_history(
            task_list_id=LIST_ID, user_id=OWNER
        )

        assert entries == []
        assert lists.calls == [(LIST_ID, OWNER)]

    async def test_an_unknown_list_is_refused(self) -> None:
        with pytest.raises(TaskListNotFoundError):
            await _service(
                FakeHistoryRepo(owner=None), FakeTaskListRepo(None)
            ).get_task_list_history(task_list_id=LIST_ID, user_id=OWNER)

    async def test_another_users_unprojected_list_is_refused(self) -> None:
        with pytest.raises(TaskListNotFoundError):
            await _service(
                FakeHistoryRepo(owner=None), FakeTaskListRepo(_live_list())
            ).get_task_list_history(task_list_id=LIST_ID, user_id=INTRUDER)


class TestTheReadAndTheCount:
    async def test_it_reads_the_task_list_root_with_the_page_unchanged(self) -> None:
        history = FakeHistoryRepo(owner=OWNER)

        await _service(history, FakeTaskListRepo(None)).get_task_list_history(
            task_list_id=LIST_ID, user_id=OWNER, limit=5, offset=10
        )

        assert history.owner_calls == [("task_list", LIST_ID)]
        assert history.aggregate_calls == [("task_list", LIST_ID, 5, 10)]

    async def test_the_count_is_authorised_the_same_way(self) -> None:
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__created__")])

        with pytest.raises(TaskListNotFoundError):
            await _service(history, FakeTaskListRepo(None)).get_task_list_history_count(
                task_list_id=LIST_ID, user_id=INTRUDER
            )

        assert history.count_calls == []

    async def test_the_count_reads_the_task_list_root(self) -> None:
        history = FakeHistoryRepo(
            owner=OWNER, entries=[_entry("__created__"), _entry("name")]
        )

        total = await _service(
            history, FakeTaskListRepo(None)
        ).get_task_list_history_count(task_list_id=LIST_ID, user_id=OWNER)

        assert total == 2
        assert history.count_calls == [("task_list", LIST_ID)]
