"""Unit tests for ``TaskListService.delete_task_list``, against mocked ports.

What is pinned here is the service's own part of a list delete — the order it
calls the ports in, what it refuses before writing, and what it announces:

- deletes of one list are serialised first, then the list is read under a
  **share** lock, its tasks are released, the list row is deleted, and only
  then is anything published;
- a missing (or another user's) list and an archived list are refused before
  any task is touched, and nothing is published;
- every deleted task announces ``TaskDeleted``, every kept task announces that
  it left the list, and one ``TaskListDeleted`` closes the list's history — in
  that order, carrying the provenance the caller gave;
- the service answers with what the repository released.

The locking itself, the split between deleted and kept tasks, and the outbox
rows are proved against a real database in
``tests/integration/tasks/test_task_list_service_integration.py``.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskList,
    TaskListArchivedError,
    TaskListDeletion,
    TaskListNotFoundError,
)

from app.core.tasks.models.events import (
    DomainEvent,
    TaskDeleted,
    TaskListMembershipChanged,
)
from app.core.tasks.models.task_list_events import TaskListDeleted
from app.core.tasks.services.task_list_service import TaskListService

pytestmark = pytest.mark.unit

USER_ID = "user-1"
LIST_ID = 7
NAME = "Packing"


def _list(*, archived: bool = False) -> TaskList:
    return TaskList(
        id=LIST_ID,
        user_id=USER_ID,
        name=NAME,
        position=0,
        archived_at=(
            datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC) if archived else None
        ),
    )


class _Ports:
    """The three ports, attached to one parent so call order is recorded."""

    def __init__(
        self,
        *,
        stored: TaskList | None,
        released: TaskListDeletion | None = None,
    ) -> None:
        self.calls = MagicMock()
        self.task_list_repo = AsyncMock()
        self.task_repo = AsyncMock()
        self.event_publisher = AsyncMock()
        self.task_list_repo.find_by_id_for_share.return_value = stored
        self.task_repo.release_list_tasks.return_value = released or (
            TaskListDeletion(
                task_list_id=LIST_ID, deleted_task_ids=(), kept_task_ids=()
            )
        )
        self.calls.attach_mock(self.task_list_repo, "task_list_repo")
        self.calls.attach_mock(self.task_repo, "task_repo")
        self.calls.attach_mock(self.event_publisher, "event_publisher")

    def service(self) -> TaskListService:
        return TaskListService(
            task_list_repo=self.task_list_repo,
            event_publisher=self.event_publisher,
            task_repo=self.task_repo,
        )

    def call_names(self) -> list[str]:
        return [call[0] for call in self.calls.mock_calls if call[0]]

    def published(self) -> list[DomainEvent]:
        return [call.args[0] for call in self.event_publisher.publish.await_args_list]


async def _delete(
    ports: _Ports,
    *,
    source: Provenance = Provenance.UI,
    changed_by: str = "ui",
) -> TaskListDeletion:
    return await ports.service().delete_task_list(
        user_id=USER_ID,
        task_list_id=LIST_ID,
        transaction=AsyncMock(),
        source=source,
        changed_by=changed_by,
    )


class TestTheOrderOfADelete:
    async def test_it_locks_the_list_shared_then_releases_then_deletes_then_publishes(
        self,
    ) -> None:
        """Releasing the tasks first is what the ``RESTRICT`` foreign key needs,
        and publishing last means only a delete that finished is announced."""
        ports = _Ports(stored=_list())

        await _delete(ports)

        assert ports.call_names() == [
            "task_list_repo.serialize_deletes",
            "task_list_repo.find_by_id_for_share",
            "task_repo.release_list_tasks",
            "task_list_repo.delete",
            "event_publisher.publish",
        ]
        ports.task_list_repo.serialize_deletes.assert_awaited_once_with(LIST_ID)
        ports.task_list_repo.find_by_id_for_share.assert_awaited_once_with(
            LIST_ID, USER_ID
        )
        ports.task_repo.release_list_tasks.assert_awaited_once_with(LIST_ID, USER_ID)
        ports.task_list_repo.delete.assert_awaited_once_with(LIST_ID, USER_ID)


class TestRefusals:
    async def test_a_missing_or_foreign_list_is_not_found_and_nothing_happens(
        self,
    ) -> None:
        ports = _Ports(stored=None)

        with pytest.raises(TaskListNotFoundError):
            await _delete(ports)

        ports.task_repo.release_list_tasks.assert_not_awaited()
        ports.task_list_repo.delete.assert_not_awaited()
        ports.event_publisher.publish.assert_not_awaited()

    async def test_an_archived_list_is_refused_before_any_task_is_touched(
        self,
    ) -> None:
        """Read-only until unarchived: deleting is a write like any other."""
        ports = _Ports(stored=_list(archived=True))

        with pytest.raises(TaskListArchivedError):
            await _delete(ports)

        ports.task_repo.release_list_tasks.assert_not_awaited()
        ports.task_list_repo.delete.assert_not_awaited()
        ports.event_publisher.publish.assert_not_awaited()


class TestWhatADeleteAnnounces:
    async def test_an_empty_list_announces_only_its_own_deletion(self) -> None:
        ports = _Ports(stored=_list())

        await _delete(ports)

        [event] = ports.published()
        assert isinstance(event, TaskListDeleted)
        assert event.event_data == {
            "task_list_id": LIST_ID,
            "user_id": USER_ID,
            "name": NAME,
            "deleted_task_count": 0,
            "kept_task_count": 0,
            "source": "ui",
            "changed_by": "ui",
        }

    async def test_deleted_then_kept_tasks_are_announced_before_the_list(
        self,
    ) -> None:
        ports = _Ports(
            stored=_list(),
            released=TaskListDeletion(
                task_list_id=LIST_ID, deleted_task_ids=(3, 5), kept_task_ids=(4,)
            ),
        )

        await _delete(ports, source=Provenance.MCP, changed_by="mcp")

        events = ports.published()
        assert [type(each) for each in events] == [
            TaskDeleted,
            TaskDeleted,
            TaskListMembershipChanged,
            TaskListDeleted,
        ]
        assert [each.aggregate_id for each in events] == [3, 5, 4, LIST_ID]
        kept = events[2]
        assert kept.event_data["changed_fields"] == {"task_list_id": (LIST_ID, None)}
        assert events[3].event_data["deleted_task_count"] == 2
        assert events[3].event_data["kept_task_count"] == 1
        assert {each.event_data["user_id"] for each in events} == {USER_ID}
        assert {each.event_data["source"] for each in events} == {"mcp"}
        assert {each.event_data["changed_by"] for each in events} == {"mcp"}

    async def test_it_answers_with_what_was_released(self) -> None:
        released = TaskListDeletion(
            task_list_id=LIST_ID, deleted_task_ids=(3,), kept_task_ids=(4, 6)
        )
        ports = _Ports(stored=_list(), released=released)

        assert await _delete(ports) == released
