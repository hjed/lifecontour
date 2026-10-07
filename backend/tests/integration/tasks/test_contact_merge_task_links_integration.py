"""A contact merge moves a task's people onto the survivor (ITER18-006 Phase 1).

**The defect these tests pin down was invisible.** ``task_contacts.contact_id``
is ``ON DELETE CASCADE``, and a contact merge ends by deleting the absorbed
contact row — so every task link that contact held was destroyed by the
database, quietly, with no error anywhere. A task that referenced the absorbed
person ended up referencing nobody. Nothing failed, which is why it survived
ITER18-001's twenty-two phases and ITER18-003's nine.

**Why the real schema.** Two of the four things being asserted are properties of
the database rather than of any Python: ``PRIMARY KEY (task_id, contact_id)``
turns a task linked to *both* contacts into a duplicate-key violation unless the
duplicate is removed before the re-point runs, and the ``CASCADE`` above is what
makes the ordering matter at all. Neither is observable against a double.

The file is in two halves. The first drives
:class:`SqlTaskContactRepository` and :class:`TaskContactMergeService` directly,
because that is where the rows and the events are decided. The second drives
``ContactMergeService.merge_contacts`` — the operation the user actually
performs — so the ordering inside the merge is asserted against the merge rather
than against a plan for it.
"""

import pytest
import pytest_asyncio
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_relationship_repository import (
    SqlContactRelationshipRepository,
)
from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.tasks.adapters.sql.task_contact_repository import (
    SqlTaskContactRepository,
)
from app.core.tasks.models.events import contact_field_name
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_contact,
    create_task,
    link_contact,
    linked_contact_ids,
    stored_anchors,
    stored_status,
    stored_text,
    task_events,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def task_contact_repo(
    async_connection: AsyncConnection,
) -> SqlTaskContactRepository:
    return SqlTaskContactRepository(async_connection)


@pytest_asyncio.fixture
async def merge(
    async_connection: AsyncConnection,
    task_contact_repo: SqlTaskContactRepository,
) -> TaskContactMergeService:
    """The tasks domain's half, over the real publisher on this connection.

    The real ``OutboxEventPublisher`` rather than a double, because the point of
    the events here is that they are written by the same transaction as the rows
    they describe — which a double cannot demonstrate.
    """
    return TaskContactMergeService(
        task_contact_repo=task_contact_repo,
        event_publisher=OutboxEventPublisher(async_connection),
    )


@pytest_asyncio.fixture
async def contact_merge(
    async_connection: AsyncConnection,
    merge: TaskContactMergeService,
) -> ContactMergeService:
    """The whole merge, over real adapters — the operation the user performs."""
    return ContactMergeService(
        contact_repo=SqlContactRepository(async_connection),
        relationship_repo=SqlContactRelationshipRepository(async_connection),
        journal_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        event_publisher=OutboxEventPublisher(async_connection),
        history_repo=SqlFieldHistoryRepository(async_connection),
        sync_metadata_repo=SyncMetadataRepository(async_connection),
        task_merge_service=merge,
    )


@pytest_asyncio.fixture
async def people(async_connection: AsyncConnection) -> tuple[int, int]:
    """The absorbed contact and the survivor, as ``(absorbed, survivor)``."""
    absorbed = await create_contact(async_connection, first_name="Sarah")
    survivor = await create_contact(async_connection, first_name="Sara")
    return absorbed, survivor


async def seed_task(
    connection: AsyncConnection,
    anchors: tuple[int, int],
    *,
    contact_ids: tuple[int, ...] = (),
    text: str = "return the book",
) -> int:
    """A task with the given people already on it."""
    creating_id, due_id = anchors
    task_id = await create_task(
        connection,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        text=text,
    )
    for contact_id in contact_ids:
        await link_contact(connection, task_id=task_id, contact_id=contact_id)
    return task_id


class TestTheLinksMove:
    """Criterion 1: a task referencing the absorbed contact references the survivor."""

    async def test_a_link_is_repointed_onto_the_survivor(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        assert await linked_contact_ids(async_connection, task_id) == [survivor]

    async def test_a_task_linked_to_both_collapses_to_one_row(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """The composite primary key makes this a hard error, not a cosmetic one.

        Without the collapse the re-point's ``UPDATE`` writes a second
        ``(task_id, survivor)`` row and PostgreSQL refuses it, failing the whole
        merge — and ``ON CONFLICT`` cannot rescue an ``UPDATE``, so the duplicate
        has to be gone *before* it runs. **Deleting the collapse statement must
        fail this test**, which is the one thing asked of it.
        """
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed, survivor)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        assert await linked_contact_ids(async_connection, task_id) == [survivor]

    async def test_two_tasks_both_move(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """One statement per table, however many tasks the person is on."""
        absorbed, survivor = people
        first = await seed_task(async_connection, task_anchors, contact_ids=(absorbed,))
        second = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,), text="ring back"
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        assert await linked_contact_ids(async_connection, first) == [survivor]
        assert await linked_contact_ids(async_connection, second) == [survivor]

    async def test_repointing_a_contact_onto_itself_changes_nothing(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """A no-op rather than a self-collapse.

        ``merge_contacts`` refuses a self-merge before it gets here, so this is
        about the port standing on its own: the collapse statement would
        otherwise match every link against itself and delete the lot.
        """
        absorbed, _ = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=absorbed,
            transaction=async_connection,
        )

        assert await linked_contact_ids(async_connection, task_id) == [absorbed]
        assert await task_events(async_connection, task_id=task_id) == []


class TestBystandersAreUntouched:
    """Criterion 3: a merge changes who a task references, and nothing else."""

    async def test_a_task_linked_to_neither_contact_is_left_alone(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        absorbed, survivor = people
        other = await create_contact(async_connection, first_name="Someone else")
        task_id = await seed_task(async_connection, task_anchors, contact_ids=(other,))

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        assert await linked_contact_ids(async_connection, task_id) == [other]
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_a_task_already_on_the_survivor_alone_is_left_alone(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """Nothing moved for it, so nothing is announced about it.

        An event here would put "Sara was added" in that task's history for a
        merge that did not touch it.
        """
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(survivor,)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        assert await linked_contact_ids(async_connection, task_id) == [survivor]
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_the_task_itself_does_not_change(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """Status, text and both anchors, on a task the merge *did* move.

        A merge is a change of who a task references, nothing else — so this is
        asserted on the moved task rather than only on the bystander, where it
        would hold trivially.
        """
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        assert await stored_status(async_connection, task_id) == TaskStatus.NOT_DONE
        assert await stored_text(async_connection, task_id) == "return the book"
        assert await stored_anchors(async_connection, task_id) == task_anchors


class TestTheMoveIsAnnounced:
    """Criterion 4: the survivor's activity history gains the record."""

    async def test_a_moved_task_publishes_both_halves(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """The departure *and* the arrival, read back out of the outbox.

        Both are needed and for different readers: the arrival is what puts the
        task on the survivor's activity feed, and the departure is what stops
        the absorbed contact's removal reading as an unexplained gap.
        """
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["user_id"] == USER_ID
        assert event.payload["changed_fields"] == {
            contact_field_name(absorbed): [absorbed, None],
            contact_field_name(survivor): [None, survivor],
        }

    async def test_a_collapsed_task_publishes_the_departure_alone(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed, survivor)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.payload["changed_fields"] == {
            contact_field_name(absorbed): [absorbed, None]
        }

    async def test_the_events_go_out_in_task_id_order(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """So one merge's history is the same on every run.

        The outbox is read back in ``(occurred_at, id)`` order, and nothing about
        two ``RETURNING`` clauses guarantees the rows arrive sorted.
        """
        absorbed, survivor = people
        first = await seed_task(async_connection, task_anchors, contact_ids=(absorbed,))
        second = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,), text="ring back"
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
        )

        assert [
            event.aggregate_id for event in await task_events(async_connection)
        ] == [
            min(first, second),
            max(first, second),
        ]

    async def test_the_merging_actor_reaches_the_moved_task(
        self,
        async_connection: AsyncConnection,
        merge: TaskContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,)
        )

        await merge.repoint_contact_links(
            source_contact_id=absorbed,
            survivor_contact_id=survivor,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="agent",
        )

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "agent"


class TestTheWholeMergeCarriesThePeople:
    """The operation the user performs, with the source contact really deleted."""

    async def test_merging_moves_the_task_onto_the_survivor(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """The defect, end to end.

        Before this phase the merge's ``DELETE FROM contacts`` cascaded the link
        away and this task came back referencing nobody.
        """
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,)
        )

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection, user_id=TEST_USER_ID
        )

        assert await linked_contact_ids(async_connection, task_id) == [survivor]

    async def test_merging_collapses_a_task_linked_to_both(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """The merge must not fail on the composite primary key."""
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed, survivor)
        )

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection, user_id=TEST_USER_ID
        )

        assert await linked_contact_ids(async_connection, task_id) == [survivor]

    async def test_a_failed_merge_leaves_the_links_exactly_as_they_were(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Criterion 2: the re-point is inside the merge's own unit of work.

        The merge is failed *after* the re-point has already moved the rows —
        the source contact's deletion is made to raise — because that is the
        only ordering that can tell an atomic re-point from one that happens to
        run first. A failure before the re-point would pass whether or not the
        two shared a transaction.
        """
        absorbed, survivor = people
        task_id = await seed_task(
            async_connection, task_anchors, contact_ids=(absorbed,)
        )
        monkeypatch.setattr(contact_merge.contact_repo, "delete", _raises)

        with pytest.raises(RuntimeError, match="merge failed"):
            await contact_merge.merge_contacts(
                survivor, absorbed, transaction=async_connection, user_id=TEST_USER_ID
            )

        assert await linked_contact_ids(async_connection, task_id) == [absorbed]

    async def test_a_merge_that_moved_no_task_still_succeeds(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        people: tuple[int, int],
    ) -> None:
        """Most merges: neither person is on a task, and nothing is announced."""
        absorbed, survivor = people

        merged = await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection, user_id=TEST_USER_ID
        )

        assert merged.id == survivor
        assert await task_events(async_connection) == []


async def _raises(_contact_id: int, *, user_id: str) -> None:
    """Stands in for the source contact's deletion, failing the merge."""
    raise RuntimeError("merge failed")
