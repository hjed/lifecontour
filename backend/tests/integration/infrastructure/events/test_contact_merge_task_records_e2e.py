"""A merge carries the absorbed contact's task records (ITER18-006 Phase 2).

Phase 1 stopped a merge destroying a task's people. It did not move what those
links had already written down: a contact's task record is filed on the **task**
and names the person only in ``field_name``, so deleting the absorbed contact
leaves every one of their records intact and permanently unreachable. Phase 2
rewrites the name.

**Why this file sits with the projection tests rather than beside Phase 1's.**
The thing being asserted spans the merge transaction *and* the projection that
runs after it commits, and that pairing is the whole difficulty of this phase.
Phase 1 announces the merge with one ``TaskUpdated`` per task, whose departure
half projects a ``contact:{absorbed}`` row **after** the merge has committed —
out of reach of any statement inside it. The decision this phase took is that
the row is right where it belongs and must not move, and the only way to assert
a decision about ordering across a commit boundary is to drive the real relay
and the real consumer. So they are driven, here, where they already live.

The row mechanics — dedupe, idempotence, preservation, scope — are
``TestAMergeCarriesTheTaskRecords`` in the history repository's own integration
file. What is asserted here is the operation a person performs.
"""

import pytest
import pytest_asyncio
from core_shared.stream_client import StreamClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_relationship_repository import (
    SqlContactRelationshipRepository,
)
from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
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
from tests.integration.infrastructure.events.projection_harness import (
    relay_and_project,
)
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_contact,
    create_task,
    link_contact,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def history_repo(
    async_connection: AsyncConnection,
) -> SqlFieldHistoryRepository:
    return SqlFieldHistoryRepository(async_connection)


@pytest_asyncio.fixture
async def contact_merge(
    async_connection: AsyncConnection,
    history_repo: SqlFieldHistoryRepository,
) -> ContactMergeService:
    """The whole merge over real adapters — the operation the user performs.

    The same assembly Phase 1's integration file uses, including the real
    ``OutboxEventPublisher`` on this connection: the events these tests relay
    have to be written by the same transaction as the rows they describe, and a
    double would prove nothing about whether they are.
    """
    return ContactMergeService(
        contact_repo=SqlContactRepository(async_connection),
        relationship_repo=SqlContactRelationshipRepository(async_connection),
        journal_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        event_publisher=OutboxEventPublisher(async_connection),
        history_repo=history_repo,
        sync_metadata_repo=SyncMetadataRepository(async_connection),
        task_merge_service=TaskContactMergeService(
            task_contact_repo=SqlTaskContactRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
        ),
    )


@pytest_asyncio.fixture
async def people(async_connection: AsyncConnection) -> tuple[int, int]:
    """The absorbed contact and the survivor, as ``(absorbed, survivor)``."""
    absorbed = await create_contact(async_connection, first_name="Sarah")
    survivor = await create_contact(async_connection, first_name="Sara")
    return absorbed, survivor


async def seed_task_with(
    connection: AsyncConnection,
    history_repo: SqlFieldHistoryRepository,
    anchors: tuple[int, int],
    *,
    contact_ids: tuple[int, ...],
    text_: str = "return the book",
    event_id: str | None = None,
) -> int:
    """A task these people are on, with the record the link already wrote.

    Both halves matter and they are separate rows in separate tables: the
    ``task_contacts`` link is what Phase 1 moves, and the ``field_history`` row
    is what this phase moves. Seeding the history through ``record_change`` is
    how every other test in this suite puts a projected row in place, and it is
    what the projection itself calls.
    """
    creating_id, due_id = anchors
    task_id = await create_task(
        connection,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        text=text_,
    )
    for contact_id in contact_ids:
        await link_contact(connection, task_id=task_id, contact_id=contact_id)
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=contact_field_name(contact_id),
                old_value=None,
                new_value=str(contact_id),
                changed_by="ui",
                event_id=event_id or f"evt-linked-{task_id}-{contact_id}",
                user_id=USER_ID,
            )
        )
    return task_id


async def feed(
    history_repo: SqlFieldHistoryRepository, contact_id: int
) -> list[tuple[str, str | None, str | None]]:
    """One person's task records, as ``(field_name, old_value, new_value)``.

    Their contact-level rows are read out deliberately. A merge also writes a
    ``merged_from`` row on the survivor and moves the absorbed contact's own
    edits across, both of which have been true since ITER13 and neither of which
    this phase changes. Leaving them in would make every assertion below a
    statement about two features at once.
    """
    entries = await history_repo.get_history_for_aggregate(
        "contact", contact_id, reader_user_id=USER_ID
    )
    return [
        (e.field_name, e.old_value, e.new_value)
        for e in entries
        if e.entity_type == "task"
    ]


async def task_feed_field_names(
    history_repo: SqlFieldHistoryRepository, task_id: int
) -> list[str]:
    """The task's own history, which reads every field name filed against it."""
    entries = await history_repo.get_history_for_aggregate("task", task_id)
    return [e.field_name for e in entries]


class TestTheRecordsReachTheSurvivor:
    """Criterion 5: the unified record carries both people's trail."""

    async def test_the_absorbed_contacts_task_record_is_on_the_survivors_feed(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        history_repo: SqlFieldHistoryRepository,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        absorbed, survivor = people
        task_id = await seed_task_with(
            async_connection, history_repo, task_anchors, contact_ids=(absorbed,)
        )

        assert await feed(history_repo, survivor) == []

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection
        )

        assert await feed(history_repo, survivor) == [
            (contact_field_name(survivor), None, str(absorbed))
        ]
        assert await task_feed_field_names(history_repo, task_id) == [
            contact_field_name(survivor)
        ]

    async def test_the_record_outlives_the_contact_it_belonged_to(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        history_repo: SqlFieldHistoryRepository,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """The defect stated as what it costs, rather than as a row count.

        ``field_history`` has no foreign key to ``contacts``, so the absorbed
        contact's records are not deleted by the merge — they are stranded,
        which is worse, because nothing raises and nothing can ever read them
        again. The assertion that the source row is gone is what makes the
        assertion above mean something.
        """
        absorbed, survivor = people
        await seed_task_with(
            async_connection, history_repo, task_anchors, contact_ids=(absorbed,)
        )

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection
        )

        gone = await async_connection.execute(
            text("SELECT COUNT(*) FROM contacts WHERE id = :id"), {"id": absorbed}
        )
        stranded = await async_connection.execute(
            text("SELECT COUNT(*) FROM field_history WHERE field_name = :fn"),
            {"fn": contact_field_name(absorbed)},
        )
        assert gone.scalar_one() == 0
        assert stranded.scalar_one() == 0

    async def test_a_task_both_people_were_on_does_not_duplicate(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        history_repo: SqlFieldHistoryRepository,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        """One event naming both people is one row after the merge, not a failure.

        The pair shares an ``event_id`` because one action put both of them on
        the task, so once the absorbed row takes the survivor's field name the
        two agree on all four columns of ``ux_field_history_event_dedup``.
        Without the statement's conflict clause this merge raises instead of
        completing.
        """
        absorbed, survivor = people
        await seed_task_with(
            async_connection,
            history_repo,
            task_anchors,
            contact_ids=(absorbed, survivor),
            event_id="evt-created-with-both",
        )

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection
        )

        assert await feed(history_repo, survivor) == [
            (contact_field_name(survivor), None, str(survivor))
        ]
        # The absorbed name is gone rather than kept alongside: a collapse, not
        # a merge that quietly left the second row behind under a dead id.
        remaining = await async_connection.execute(
            text("SELECT COUNT(*) FROM field_history WHERE field_name = :fn"),
            {"fn": contact_field_name(absorbed)},
        )
        assert remaining.scalar_one() == 0

    async def test_a_third_persons_records_are_left_alone(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        history_repo: SqlFieldHistoryRepository,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
    ) -> None:
        absorbed, survivor = people
        bystander = await create_contact(async_connection, first_name="Someone else")
        await seed_task_with(
            async_connection,
            history_repo,
            task_anchors,
            contact_ids=(absorbed, bystander),
        )

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection
        )

        assert await feed(history_repo, bystander) == [
            (contact_field_name(bystander), None, str(bystander))
        ]
        # Stated as a pair, so the test cannot pass by the statement doing
        # nothing at all: one person's records moved and the other's did not.
        assert await feed(history_repo, survivor) == [
            (contact_field_name(survivor), None, str(absorbed))
        ]


class TestTheMergesOwnAnnouncementStaysWhereItBelongs:
    """The decision this phase had to take, asserted across the commit boundary.

    Phase 1's ``TaskUpdated`` projects a departure row naming the **absorbed**
    contact, and it is written after the merge commits, so no statement inside
    the merge can reach it. That is the correct outcome rather than a gap:

    - The row is not stranded. A task's own history reads every field name filed
      against it, so this is the task's only record of who it used to reference.
    - Moved onto the survivor it would read as a removal — the front end renders
      a ``contact:`` row with no new value as "Unlinked from a task" — paired
      with the arrival row from the same merge. The event would have to lie.
    """

    async def test_the_survivor_gains_the_record_and_the_arrival_but_no_removal(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        history_repo: SqlFieldHistoryRepository,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        absorbed, survivor = people
        await seed_task_with(
            async_connection, history_repo, task_anchors, contact_ids=(absorbed,)
        )

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-contact-merge"
        )

        entries = await feed(history_repo, survivor)
        assert sorted(entries) == sorted(
            [
                # The record the absorbed contact's link had already written,
                # now readable on the survivor's feed.
                (contact_field_name(survivor), None, str(absorbed)),
                # The merge's own arrival half, projected after the commit.
                (contact_field_name(survivor), None, str(survivor)),
            ]
        )
        # No removal: nothing on this feed says the survivor left a task.
        assert [e for e in entries if e[2] is None] == []

    async def test_the_departure_half_is_on_the_tasks_own_history(
        self,
        async_connection: AsyncConnection,
        contact_merge: ContactMergeService,
        history_repo: SqlFieldHistoryRepository,
        people: tuple[int, int],
        task_anchors: tuple[int, int],
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Where the row goes instead, and why leaving it there loses nothing."""
        absorbed, survivor = people
        task_id = await seed_task_with(
            async_connection, history_repo, task_anchors, contact_ids=(absorbed,)
        )

        await contact_merge.merge_contacts(
            survivor, absorbed, transaction=async_connection
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-contact-merge"
        )

        assert sorted(await task_feed_field_names(history_repo, task_id)) == sorted(
            [
                # Moved by this phase, before the commit.
                contact_field_name(survivor),
                # The merge's announcement, projected after it.
                contact_field_name(absorbed),
                contact_field_name(survivor),
            ]
        )
