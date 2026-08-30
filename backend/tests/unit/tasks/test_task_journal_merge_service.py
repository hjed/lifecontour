"""Unit tests for the tasks domain's half of a journal merge.

This service exists for one reason, and it is a boundary reason: the write that
moves a task's links lives in the journal domain, and the event announcing it
belongs to the tasks domain. Rather than hand ``JournalMergeService`` the
ability to construct task events, the merge calls this — one seam, on the side
that owns the vocabulary.

So what is asserted here is the translation, not the SQL: that every task the
repository reports becomes exactly one event, that a merge which moved nothing
stays silent, that the two journals reach the payload the right way round, and
that the actor who performed the merge reaches the tasks it moved.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskJournalRepointing

from app.core.tasks.models.events import TaskJournalLinksRepointed
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from tests.unit.tasks.task_doubles import (
    ABSORBED_JOURNAL_ID,
    SURVIVING_JOURNAL_ID,
    TASK_ID,
    USER_ID,
)

OTHER_TASK_ID = TASK_ID + 1


@pytest.fixture
def anchor_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.repoint_journal_links.return_value = []
    return repo


@pytest.fixture
def event_publisher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(
    anchor_repo: AsyncMock, event_publisher: AsyncMock
) -> TaskJournalMergeService:
    return TaskJournalMergeService(
        task_anchor_repo=anchor_repo, event_publisher=event_publisher
    )


def published(event_publisher: AsyncMock) -> list[TaskJournalLinksRepointed]:
    """Every event handed to the publisher, in the order it was handed over."""
    return [call.args[0] for call in event_publisher.publish.await_args_list]


async def repoint(service: TaskJournalMergeService, **kwargs) -> None:
    """Perform the merge's task half over the shared journal constants."""
    await service.repoint_journal_links(
        source_journal_id=ABSORBED_JOURNAL_ID,
        target_journal_id=SURVIVING_JOURNAL_ID,
        transaction=AsyncMock(),
        **kwargs,
    )


class TestTheRepointIsDelegated:
    """The row work stays in the repository; this service only announces it."""

    async def test_it_moves_the_links_through_the_port(
        self, service: TaskJournalMergeService, anchor_repo: AsyncMock
    ) -> None:
        await repoint(service)

        anchor_repo.repoint_journal_links.assert_awaited_once_with(
            source_journal_id=ABSORBED_JOURNAL_ID,
            target_journal_id=SURVIVING_JOURNAL_ID,
        )

    async def test_the_journals_are_not_passed_the_wrong_way_round(
        self, service: TaskJournalMergeService, anchor_repo: AsyncMock
    ) -> None:
        """Two ints of the same type, so only an assertion separates them.

        Swapping them moves every link onto the journal that is about to be
        deleted, and the merge then fails on the anchor foreign key — which is
        the failure this phase must not introduce while adding an event.
        """
        await repoint(service)
        kwargs = anchor_repo.repoint_journal_links.await_args.kwargs

        assert kwargs["source_journal_id"] == ABSORBED_JOURNAL_ID
        assert kwargs["target_journal_id"] == SURVIVING_JOURNAL_ID


class TestOneEventPerAffectedTask:
    """``field_history`` aggregates under a task id, so the event does too."""

    async def test_a_moved_task_is_announced(
        self,
        service: TaskJournalMergeService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        anchor_repo.repoint_journal_links.return_value = [
            TaskJournalRepointing(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_moved=True
            )
        ]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_type == "TaskJournalLinksRepointed"
        assert event.aggregate_id == TASK_ID
        assert event.event_data["changed_fields"] == {
            "due_journal_id": (ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID)
        }

    async def test_each_task_gets_its_own_event_in_the_order_reported(
        self,
        service: TaskJournalMergeService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """Per task, not one event listing them all.

        A batch event would have to be aggregated under something, and the only
        candidates are the two journals — which is exactly where the merge
        already publishes and exactly why the affected tasks' histories say
        nothing today.
        """
        anchor_repo.repoint_journal_links.return_value = [
            TaskJournalRepointing(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_moved=True
            ),
            TaskJournalRepointing(
                task_id=OTHER_TASK_ID, user_id=USER_ID, creating_anchor_moved=True
            ),
        ]

        await repoint(service)

        assert [event.aggregate_id for event in published(event_publisher)] == [
            TASK_ID,
            OTHER_TASK_ID,
        ]

    async def test_a_merge_that_moved_no_task_publishes_nothing(
        self, service: TaskJournalMergeService, event_publisher: AsyncMock
    ) -> None:
        """Most merges. Silence here is the difference between a history that
        records what happened and one full of lines about journals the user's
        tasks were never on."""
        await repoint(service)

        event_publisher.publish.assert_not_awaited()

    async def test_the_event_names_both_journals(
        self,
        service: TaskJournalMergeService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        anchor_repo.repoint_journal_links.return_value = [
            TaskJournalRepointing(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_moved=True
            )
        ]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_data["source_journal_id"] == ABSORBED_JOURNAL_ID
        assert event.event_data["target_journal_id"] == SURVIVING_JOURNAL_ID

    async def test_the_owner_comes_from_the_repository_not_the_caller(
        self,
        service: TaskJournalMergeService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """The merge never read the task, so it cannot supply this.

        It reached these tasks through a journal, and a task's owner has to
        travel on the event because a task-scoped history read resolves a
        hard-deleted task without a row to join back to.
        """
        anchor_repo.repoint_journal_links.return_value = [
            TaskJournalRepointing(
                task_id=TASK_ID, user_id="somebody-else", due_anchor_moved=True
            )
        ]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_data["user_id"] == "somebody-else"


class TestProvenanceReachesTheMovedTasks:
    """A merge in the browser and one over MCP are distinguishable per task."""

    async def test_the_actor_is_carried_onto_every_event(
        self,
        service: TaskJournalMergeService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        anchor_repo.repoint_journal_links.return_value = [
            TaskJournalRepointing(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_moved=True
            ),
            TaskJournalRepointing(
                task_id=OTHER_TASK_ID, user_id=USER_ID, due_anchor_moved=True
            ),
        ]

        await repoint(service, source=Provenance.MCP, changed_by="mcp")

        assert [
            (event.event_data["source"], event.event_data["changed_by"])
            for event in published(event_publisher)
        ] == [("mcp", "mcp"), ("mcp", "mcp")]

    async def test_provenance_defaults_to_the_system(
        self,
        service: TaskJournalMergeService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """A caller that says nothing gets the same default every task write has.

        Not because ``system`` is right for a merge — it is not, and all three
        surfaces pass a real actor — but because the alternative is a required
        argument on a method the journal domain calls, which turns "who merged?"
        into a question the journal domain has to answer at construction time
        rather than at the point it knows.
        """
        anchor_repo.repoint_journal_links.return_value = [
            TaskJournalRepointing(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_moved=True
            )
        ]

        await repoint(service)

        (event,) = published(event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"


class TestTheEventsRideTheMergesTransaction:
    async def test_each_event_carries_the_connection_it_was_given(
        self,
        service: TaskJournalMergeService,
        anchor_repo: AsyncMock,
        event_publisher: AsyncMock,
    ) -> None:
        """So a merge that fails leaves no task event behind it.

        The publisher inserts on the connection it was constructed with rather
        than on this field, but the events carry it for the same conformance
        every other task event does, and the integration test that fails a merge
        mid-flight is what actually proves the rollback.
        """
        transaction = AsyncMock()
        anchor_repo.repoint_journal_links.return_value = [
            TaskJournalRepointing(
                task_id=TASK_ID, user_id=USER_ID, due_anchor_moved=True
            )
        ]

        await service.repoint_journal_links(
            source_journal_id=ABSORBED_JOURNAL_ID,
            target_journal_id=SURVIVING_JOURNAL_ID,
            transaction=transaction,
        )

        (event,) = published(event_publisher)
        assert event.transaction is transaction
