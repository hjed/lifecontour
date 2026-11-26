"""Unit tests for the tasks domain's half of a journal delete.

A journal delete is refused while a journal-only task is anchored to it, but a
task on a list never blocks it: the list task loses every link it held to the
journal instead. The row work is the repository's; this service is the seam
that announces it, one event per task, in the vocabulary the tasks domain owns —
the delete's counterpart of ``TaskJournalMergeService``.

So what is asserted here is the translation: every task the repository reports
becomes exactly one event, a delete that detached nothing stays silent, the
deleting actor reaches the tasks it changed, and the count the caller reports
is the count of tasks actually detached.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskJournalDetachment

from app.core.tasks.models.events import TaskJournalLinksRemoved
from app.core.tasks.models.task_list_events import TaskListUpdated
from app.core.tasks.services.task_journal_deletion_service import (
    TaskJournalDeletionService,
)
from tests.unit.tasks.task_doubles import DELETED_JOURNAL_ID, TASK_ID, USER_ID

OTHER_TASK_ID = TASK_ID + 1
LIST_ID = 41
OTHER_LIST_ID = 42


@pytest.fixture
def anchor_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.detach_list_tasks_from_journal.return_value = []
    repo.count_list_tasks_linked_to_journal.return_value = 0
    return repo


@pytest.fixture
def list_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.unassociate_journal.return_value = []
    return repo


@pytest.fixture
def event_publisher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(
    anchor_repo: AsyncMock, list_repo: AsyncMock, event_publisher: AsyncMock
) -> TaskJournalDeletionService:
    return TaskJournalDeletionService(
        task_anchor_repo=anchor_repo,
        task_list_repo=list_repo,
        event_publisher=event_publisher,
    )


def published(event_publisher: AsyncMock) -> list[TaskJournalLinksRemoved]:
    """Every event handed to the publisher, in the order it was handed over."""
    return [call.args[0] for call in event_publisher.publish.await_args_list]


async def remove(service: TaskJournalDeletionService, **kwargs: object) -> int:
    """Detach the list tasks from the shared deleted journal."""
    return await service.remove_list_task_links(
        journal_id=DELETED_JOURNAL_ID,
        transaction=AsyncMock(),
        **kwargs,  # type: ignore[arg-type]
    )


class TestTheDetachIsDelegated:
    async def test_it_detaches_through_the_port(
        self, service: TaskJournalDeletionService, anchor_repo: AsyncMock
    ) -> None:
        await remove(service)

        anchor_repo.detach_list_tasks_from_journal.assert_awaited_once_with(
            DELETED_JOURNAL_ID
        )


class TestOneEventPerDetachedTask:
    async def test_a_detached_task_is_announced(
        self,
        service: TaskJournalDeletionService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        anchor_repo.detach_list_tasks_from_journal.return_value = [
            TaskJournalDetachment(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_removed=True
            )
        ]

        await remove(service)

        (event,) = published(event_publisher)
        assert event.event_type == "TaskJournalLinksRemoved"
        assert event.aggregate_id == TASK_ID
        assert event.event_data["changed_fields"] == {
            "due_journal_id": (DELETED_JOURNAL_ID, None)
        }

    async def test_each_task_gets_its_own_event_in_the_order_reported(
        self,
        service: TaskJournalDeletionService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        anchor_repo.detach_list_tasks_from_journal.return_value = [
            TaskJournalDetachment(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_removed=True
            ),
            TaskJournalDetachment(
                task_id=OTHER_TASK_ID, user_id=USER_ID, link_removed=True
            ),
        ]

        await remove(service)

        assert [event.aggregate_id for event in published(event_publisher)] == [
            TASK_ID,
            OTHER_TASK_ID,
        ]

    async def test_a_delete_that_detached_nothing_publishes_nothing(
        self, service: TaskJournalDeletionService, event_publisher: AsyncMock
    ) -> None:
        """Most journals no list task links to; their delete says nothing here."""
        await remove(service)

        event_publisher.publish.assert_not_called()

    async def test_the_deleting_actor_reaches_each_event(
        self,
        service: TaskJournalDeletionService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """The delete is something a person did, so the tasks it changed carry
        that person's provenance rather than ``system``."""
        anchor_repo.detach_list_tasks_from_journal.return_value = [
            TaskJournalDetachment(
                task_id=TASK_ID, user_id=USER_ID, creating_anchor_removed=True
            )
        ]

        await remove(service, source=Provenance.MCP, changed_by="mcp")

        (event,) = published(event_publisher)
        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"


class TestTheCount:
    async def test_it_returns_how_many_tasks_were_detached(
        self, service: TaskJournalDeletionService, anchor_repo: AsyncMock
    ) -> None:
        anchor_repo.detach_list_tasks_from_journal.return_value = [
            TaskJournalDetachment(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_removed=True
            ),
            TaskJournalDetachment(
                task_id=OTHER_TASK_ID, user_id=USER_ID, link_removed=True
            ),
        ]

        assert await remove(service) == 2

    async def test_nothing_detached_is_zero(
        self, service: TaskJournalDeletionService
    ) -> None:
        assert await remove(service) == 0

    async def test_the_preview_count_comes_from_the_port(
        self, service: TaskJournalDeletionService, anchor_repo: AsyncMock
    ) -> None:
        anchor_repo.count_list_tasks_linked_to_journal.return_value = 3

        assert await service.count_list_task_links(DELETED_JOURNAL_ID) == 3
        anchor_repo.count_list_tasks_linked_to_journal.assert_awaited_once_with(
            DELETED_JOURNAL_ID
        )


def published_list_updates(event_publisher: AsyncMock) -> list[TaskListUpdated]:
    """The list events handed to the publisher, in order."""
    return [call.args[0] for call in event_publisher.publish.await_args_list]


async def unassociate(
    service: TaskJournalDeletionService,
    transaction: AsyncMock | None = None,
    **kwargs: object,
) -> None:
    """Unassociate the owner's lists from the shared deleted journal."""
    await service.unassociate_lists(
        journal_id=DELETED_JOURNAL_ID,
        user_id=USER_ID,
        transaction=transaction or AsyncMock(),
        **kwargs,  # type: ignore[arg-type]
    )


class TestListsAreUnassociated:
    """A deleted journal's lists survive, unassociated, and each says so."""

    async def test_it_unassociates_the_owners_lists_through_the_port(
        self, service: TaskJournalDeletionService, list_repo: AsyncMock
    ) -> None:
        await unassociate(service)

        list_repo.unassociate_journal.assert_awaited_once_with(
            DELETED_JOURNAL_ID, USER_ID
        )

    async def test_each_list_gets_one_event_in_the_order_reported(
        self,
        service: TaskJournalDeletionService,
        list_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        list_repo.unassociate_journal.return_value = [LIST_ID, OTHER_LIST_ID]

        await unassociate(service)

        events = published_list_updates(event_publisher)
        assert [event.event_type for event in events] == ["TaskListUpdated"] * 2
        assert [event.aggregate_id for event in events] == [LIST_ID, OTHER_LIST_ID]
        assert [event.event_data["user_id"] for event in events] == [USER_ID] * 2
        assert [event.event_data["changed_fields"] for event in events] == [
            {"associated_journal_id": (DELETED_JOURNAL_ID, None)}
        ] * 2

    async def test_a_journal_no_list_names_publishes_nothing(
        self, service: TaskJournalDeletionService, event_publisher: AsyncMock
    ) -> None:
        await unassociate(service)

        event_publisher.publish.assert_not_called()

    async def test_the_deleting_actor_and_transaction_reach_the_event(
        self,
        service: TaskJournalDeletionService,
        list_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        list_repo.unassociate_journal.return_value = [LIST_ID]
        transaction = AsyncMock()

        await unassociate(service, transaction, source=Provenance.MCP, changed_by="mcp")

        (event,) = published_list_updates(event_publisher)
        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"
        assert event.transaction is transaction
