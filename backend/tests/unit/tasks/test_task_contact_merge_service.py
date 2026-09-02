"""Unit tests for the tasks domain's half of a contact merge.

The same boundary reason ``TaskJournalMergeService`` exists for, applied to the
other merge: the write that moves a task's contact links is reached from
``ContactMergeService``, and the event announcing it belongs to the tasks
domain. The contacts domain asks for the move rather than constructing task
events itself.

What is asserted here is the translation, not the SQL: every task the repository
reports becomes exactly one event, a merge that moved nothing stays silent, the
two contacts reach the payload the right way round, and the person who performed
the merge reaches the tasks it moved.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskContactRepointing

from app.core.tasks.models.events import DomainEvent
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
)
from tests.unit.tasks.task_doubles import (
    ABSORBED_CONTACT_ID,
    SURVIVING_CONTACT_ID,
    TASK_ID,
    USER_ID,
)

OTHER_TASK_ID = TASK_ID + 1


@pytest.fixture
def contact_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.repoint_contact_links.return_value = []
    return repo


@pytest.fixture
def event_publisher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(
    contact_repo: AsyncMock, event_publisher: AsyncMock
) -> TaskContactMergeService:
    return TaskContactMergeService(
        task_contact_repo=contact_repo, event_publisher=event_publisher
    )


def moved(task_id: int = TASK_ID, *, user_id: str = USER_ID) -> TaskContactRepointing:
    """A task whose link was re-pointed onto the survivor."""
    return TaskContactRepointing(
        task_id=task_id, user_id=user_id, survivor_link_added=True
    )


def published(event_publisher: AsyncMock) -> list[DomainEvent]:
    """Every event handed to the publisher, in the order it was handed over."""
    return [call.args[0] for call in event_publisher.publish.await_args_list]


async def repoint(service: TaskContactMergeService, **kwargs) -> None:
    """Perform the merge's task half over the shared contact constants."""
    await service.repoint_contact_links(
        source_contact_id=ABSORBED_CONTACT_ID,
        survivor_contact_id=SURVIVING_CONTACT_ID,
        transaction=AsyncMock(),
        **kwargs,
    )


class TestTheRepointIsDelegated:
    """The row work stays in the repository; this service only announces it."""

    async def test_it_moves_the_links_through_the_port(
        self, service: TaskContactMergeService, contact_repo: AsyncMock
    ) -> None:
        await repoint(service)

        contact_repo.repoint_contact_links.assert_awaited_once_with(
            source_contact_id=ABSORBED_CONTACT_ID,
            survivor_contact_id=SURVIVING_CONTACT_ID,
        )

    async def test_the_contacts_are_not_passed_the_wrong_way_round(
        self, service: TaskContactMergeService, contact_repo: AsyncMock
    ) -> None:
        """Two ints of the same type, so only an assertion separates them.

        Swapping them moves every link onto the contact that is about to be
        deleted, and the ``ON DELETE CASCADE`` then destroys the lot — the exact
        defect this phase exists to repair, reintroduced by an argument order.
        """
        await repoint(service)
        kwargs = contact_repo.repoint_contact_links.await_args.kwargs

        assert kwargs["source_contact_id"] == ABSORBED_CONTACT_ID
        assert kwargs["survivor_contact_id"] == SURVIVING_CONTACT_ID


class TestOneEventPerAffectedTask:
    """``field_history`` aggregates under a task id, so the event does too."""

    async def test_a_moved_task_is_announced(
        self,
        service: TaskContactMergeService,
        contact_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        contact_repo.repoint_contact_links.return_value = [moved()]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_type == "TaskUpdated"
        assert event.aggregate_id == TASK_ID
        assert event.event_data["changed_fields"] == {
            f"contact:{ABSORBED_CONTACT_ID}": (ABSORBED_CONTACT_ID, None),
            f"contact:{SURVIVING_CONTACT_ID}": (None, SURVIVING_CONTACT_ID),
        }

    async def test_a_collapsed_task_announces_the_departure_alone(
        self,
        service: TaskContactMergeService,
        contact_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        contact_repo.repoint_contact_links.return_value = [
            TaskContactRepointing(
                task_id=TASK_ID, user_id=USER_ID, survivor_link_added=False
            )
        ]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_data["changed_fields"] == {
            f"contact:{ABSORBED_CONTACT_ID}": (ABSORBED_CONTACT_ID, None)
        }

    async def test_each_task_gets_its_own_event_in_the_order_reported(
        self,
        service: TaskContactMergeService,
        contact_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """Per task, not one event listing them all.

        A batch event would have to be aggregated under something, and the only
        candidates are the two contacts — neither of which is where a task's
        history lives.
        """
        contact_repo.repoint_contact_links.return_value = [
            moved(),
            moved(OTHER_TASK_ID),
        ]

        await repoint(service)

        assert [event.aggregate_id for event in published(event_publisher)] == [
            TASK_ID,
            OTHER_TASK_ID,
        ]

    async def test_a_merge_that_moved_no_task_publishes_nothing(
        self, service: TaskContactMergeService, event_publisher: AsyncMock
    ) -> None:
        """Most merges, since most people are on no tasks at all."""
        await repoint(service)

        event_publisher.publish.assert_not_awaited()

    async def test_the_owner_comes_from_the_repository_not_the_caller(
        self,
        service: TaskContactMergeService,
        contact_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """The merge never read the task, so it cannot supply this.

        It reached these tasks through a contact — and ``contacts`` has no owner
        column at all, so there is no acting user for the contacts domain to
        pass down even if it wanted to.
        """
        contact_repo.repoint_contact_links.return_value = [
            moved(user_id="somebody-else")
        ]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_data["user_id"] == "somebody-else"


class TestProvenanceReachesTheMovedTasks:
    """A merge in the browser and one over MCP are distinguishable per task."""

    async def test_the_actor_is_carried_onto_every_event(
        self,
        service: TaskContactMergeService,
        contact_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        contact_repo.repoint_contact_links.return_value = [
            moved(),
            moved(OTHER_TASK_ID),
        ]

        await repoint(service, source=Provenance.MCP, changed_by="mcp")

        assert [
            (event.event_data["source"], event.event_data["changed_by"])
            for event in published(event_publisher)
        ] == [("mcp", "mcp"), ("mcp", "mcp")]

    async def test_provenance_defaults_to_the_system(
        self,
        service: TaskContactMergeService,
        contact_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """A caller that says nothing gets the same default every task write has."""
        contact_repo.repoint_contact_links.return_value = [moved()]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"


class TestTheEventsRideTheMergesTransaction:
    async def test_each_event_carries_the_connection_it_was_given(
        self,
        service: TaskContactMergeService,
        contact_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """So a merge that fails leaves no task event behind it.

        The publisher inserts on the connection it was constructed with rather
        than on this field; the integration test that fails a merge mid-flight is
        what actually proves the rollback.
        """
        transaction = AsyncMock()
        contact_repo.repoint_contact_links.return_value = [moved()]

        await service.repoint_contact_links(
            source_contact_id=ABSORBED_CONTACT_ID,
            survivor_contact_id=SURVIVING_CONTACT_ID,
            transaction=transaction,
        )

        (event,) = published(event_publisher)
        assert event.transaction is transaction
