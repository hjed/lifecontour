"""Integration tests for task links surviving a journal merge.

Merge is the one journal operation the specification refuses to block: it is
what makes calendar sync usable, so a task can never stand in its way. That
puts the whole burden on re-pointing, and the schema is why these tests can
only be written against a real database:

- ``tasks.creating_journal_id`` and ``tasks.due_journal_id`` are
  ``ON DELETE RESTRICT``, so a merge that deletes the absorbed journal without
  moving them first raises an ``IntegrityError`` — the regression this phase
  exists to prevent;
- ``task_intermediate_journals.journal_id`` is ``ON DELETE CASCADE``, so an
  intermediate link that is not moved first is *silently destroyed* rather than
  refused, which no unit test can observe;
- ``task_intermediate_journals`` is keyed on ``(task_id, journal_id)``, so a
  task linked to both journals collides on the re-point unless the duplicate is
  deleted first — ``ON CONFLICT`` is unavailable on an ``UPDATE``.

Each test builds its own journals and tasks, so what exists is never in doubt.
"""

import pytest
import pytest_asyncio
from core_shared.models.tasks import Task, TaskJournalRepointing, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_contact,
    create_journal,
    create_task,
    link_intermediate_journal,
    task_events,
)

_INTERMEDIATE_IDS = (
    "SELECT journal_id FROM task_intermediate_journals "
    "WHERE task_id = :task_id ORDER BY journal_id"
)


@pytest_asyncio.fixture
async def task_repository(async_connection: AsyncConnection) -> SqlTaskRepository:
    return SqlTaskRepository(async_connection)


@pytest_asyncio.fixture
async def task_anchor_repository(
    async_connection: AsyncConnection,
) -> SqlTaskAnchorRepository:
    return SqlTaskAnchorRepository(async_connection)


@pytest_asyncio.fixture
async def task_merge_service(
    async_connection: AsyncConnection,
    task_anchor_repository: SqlTaskAnchorRepository,
) -> TaskJournalMergeService:
    return TaskJournalMergeService(
        task_anchor_repo=task_anchor_repository,
        event_publisher=OutboxEventPublisher(async_connection),
    )


@pytest_asyncio.fixture
async def merge_service(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    task_merge_service: TaskJournalMergeService,
) -> JournalMergeService:
    return JournalMergeService(
        journal_repo=journal_repository,
        event_publisher=OutboxEventPublisher(async_connection),
        task_merge_service=task_merge_service,
    )


@pytest_asyncio.fixture
async def merged_pair(journal_repository: SqlJournalRepository) -> tuple[int, int]:
    """The survivor and the journal absorbed into it, as ``(target, source)``."""
    target_id = await create_journal(journal_repository, title="Survivor")
    source_id = await create_journal(journal_repository, title="Absorbed")
    return target_id, source_id


_PUBLISHED_TYPES = "SELECT event_type FROM outbox_events ORDER BY occurred_at, id"


async def _published_types(conn: AsyncConnection) -> list[str]:
    """Every event in the outbox, in the order the relay will hand them over.

    Not filtered to ``Task%`` like the shared helper: what one of the tests below
    is about is where the task events sit *relative to the merge's own journal
    events*, which a task-only read cannot see.
    """
    result = await conn.execute(text(_PUBLISHED_TYPES))
    return [str(row[0]) for row in result.fetchall()]


async def _intermediate_ids(conn: AsyncConnection, task_id: int) -> list[int]:
    result = await conn.execute(text(_INTERMEDIATE_IDS), {"task_id": task_id})
    return [int(row[0]) for row in result.fetchall()]


async def _reload(task_repository: SqlTaskRepository, task_id: int) -> Task:
    """Read a task back through its own repository, owner-scoped as usual."""
    reloaded = await task_repository.find_by_id(task_id, USER_ID)
    assert reloaded is not None
    return reloaded


async def _link_intermediate(
    conn: AsyncConnection, task_id: int, *journal_ids: int
) -> None:
    for journal_id in journal_ids:
        await link_intermediate_journal(conn, task_id=task_id, journal_id=journal_id)


@pytest.mark.integration
class TestAnchorRepointing:
    """The two anchors move to the survivor rather than blocking the merge."""

    async def test_merging_a_tasks_creating_journal_succeeds(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The creating anchor is re-pointed instead of tripping RESTRICT."""
        target_id, source_id = merged_pair
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=due_id,
        )

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.creating_journal_id == target_id
        assert reloaded.due_journal_id == due_id

    async def test_merging_a_tasks_due_journal_succeeds(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The due anchor is re-pointed, so the task stays due somewhere real."""
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=source_id,
        )

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.due_journal_id == target_id
        assert reloaded.creating_journal_id == creating_id

    async def test_survivor_may_become_both_anchors(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
    ):
        """Creating-equals-due is permitted, and the task is otherwise unaffected.

        The specification says so explicitly: a survivor that ends up as both
        the creating and the due journal of a task is a legal outcome, not a
        conflict to resolve.
        """
        target_id, source_id = merged_pair
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=target_id,
            text="book the campsite",
        )

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.creating_journal_id == target_id
        assert reloaded.due_journal_id == target_id
        assert reloaded.text == "book the campsite"
        assert reloaded.status is TaskStatus.NOT_DONE

    async def test_nothing_references_the_deleted_source(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
    ):
        """No task row and no link row is left pointing at the absorbed journal."""
        target_id, source_id = merged_pair
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=source_id,
        )
        await _link_intermediate(async_connection, task_id, source_id)

        await merge_service.merge_journals(target_id, source_id, async_connection)

        anchored = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM tasks "
                "WHERE creating_journal_id = :id OR due_journal_id = :id"
            ),
            {"id": source_id},
        )
        linked = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM task_intermediate_journals WHERE journal_id = :id"
            ),
            {"id": source_id},
        )
        assert anchored.scalar_one() == 0
        assert linked.scalar_one() == 0

    @pytest.mark.parametrize(
        "status", [TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED]
    )
    async def test_merge_never_changes_a_tasks_status(
        self,
        status: TaskStatus,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
    ):
        """Every status survives a merge untouched, done and cancelled included."""
        target_id, source_id = merged_pair
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=source_id,
            status=status,
        )

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.status is status

    async def test_a_task_on_unrelated_journals_is_untouched(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """Re-pointing is scoped to the absorbed journal, not applied wholesale."""
        target_id, source_id = merged_pair
        elsewhere_id = await create_journal(journal_repository, title="Elsewhere")
        also_id = await create_journal(journal_repository, title="Also elsewhere")
        task_id = await create_task(
            async_connection,
            creating_journal_id=elsewhere_id,
            due_journal_id=also_id,
        )
        await _link_intermediate(async_connection, task_id, elsewhere_id)

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.creating_journal_id == elsewhere_id
        assert reloaded.due_journal_id == also_id
        assert await _intermediate_ids(async_connection, task_id) == [elsewhere_id]


@pytest.mark.integration
class TestIntermediateLinkRepointing:
    """Intermediate links move too, and duplicates collapse on the way."""

    async def test_an_intermediate_link_is_moved_not_cascaded_away(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The link survives as a link to the survivor.

        ``ON DELETE CASCADE`` means the failure mode here is silence: without
        the re-point the row is gone and the merge still reports success.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        await _link_intermediate(async_connection, task_id, source_id)

        await merge_service.merge_journals(target_id, source_id, async_connection)

        assert await _intermediate_ids(async_connection, task_id) == [target_id]

    async def test_duplicate_intermediate_links_collapse(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """A task linked to both journals ends up linked once, with no error.

        This is the test that fails if the de-duplication step is removed: the
        re-point would then try to write a second ``(task_id, target_id)`` row
        and violate the composite primary key. Neither journal is an anchor of
        this task, so the cross-role cleanup cannot mask the collision.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        await _link_intermediate(async_connection, task_id, source_id, target_id)

        await merge_service.merge_journals(target_id, source_id, async_connection)

        assert await _intermediate_ids(async_connection, task_id) == [target_id]

    async def test_an_intermediate_link_absorbed_into_an_anchor_is_dropped(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """Cross-role redundancy: the stronger role already covers the journal.

        The task was due in the survivor and mentioned the absorbed journal
        along the way. Once the two are one journal, keeping the intermediate
        link would say the same thing twice in a weaker form.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=target_id,
        )
        await _link_intermediate(async_connection, task_id, source_id)

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.due_journal_id == target_id
        assert await _intermediate_ids(async_connection, task_id) == []

    async def test_a_bystanders_redundant_link_is_left_alone(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The redundancy cleanup only touches tasks this merge moved.

        A task can hold an intermediate link to one of its own anchors without
        any merge being involved: retargeting keeps the previous due journal as
        an intermediate link, so retargeting *back* onto it produces exactly
        this shape. That is the task's own record of where it has been, and a
        merge it has nothing to do with must not delete it.

        A second task *is* anchored to the absorbed journal, so the cleanup
        statement genuinely runs; without that the merge would find nothing to
        move and never reach it.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        bystander_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=target_id,
            text="unrelated to the merge",
        )
        await _link_intermediate(async_connection, bystander_id, target_id)

        merged_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=target_id,
            text="the one the merge is about",
        )

        await merge_service.merge_journals(target_id, source_id, async_connection)

        assert await _intermediate_ids(async_connection, bystander_id) == [target_id]
        # The task the merge did move still gets both anchors on the survivor.
        moved = await _reload(task_repository, merged_id)
        assert moved.creating_journal_id == target_id
        assert moved.due_journal_id == target_id

    async def test_an_anchor_absorbed_into_an_intermediate_link_is_dropped(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The mirror direction: the anchor moves onto the linked journal."""
        target_id, source_id = merged_pair
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=due_id,
        )
        await _link_intermediate(async_connection, task_id, target_id)

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.creating_journal_id == target_id
        assert await _intermediate_ids(async_connection, task_id) == []


@pytest.mark.integration
class TestRepointingDirectly:
    """Properties of the repository method that no merge can reach.

    ``JournalMergeService`` refuses a self-merge before it gets here, so this is
    the only place the port's promise about that case can be held.
    """

    async def test_repointing_a_journal_onto_itself_changes_nothing(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The same journal as source and target must not collapse its own links.

        Every statement would otherwise read the rows it is about to write —
        the de-duplication step would match each intermediate link against
        itself and delete all of them.
        """
        journal_id = await create_journal(journal_repository, title="Only journal")
        other_id = await create_journal(journal_repository, title="Somewhere else")
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=other_id,
        )
        await _link_intermediate(async_connection, task_id, journal_id)

        await task_anchor_repository.repoint_journal_links(
            source_journal_id=journal_id, target_journal_id=journal_id
        )

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.creating_journal_id == journal_id
        assert reloaded.due_journal_id == other_id
        assert await _intermediate_ids(async_connection, task_id) == [journal_id]


@pytest.mark.integration
class TestTheRepointReportsWhatItMoved:
    """The return value, which is what the task domain publishes from.

    Asserted against the repository directly rather than through the merge:
    what a merge *publishes* is the service's business and is tested there, and
    what is checked here is that four set-based statements can say, per task,
    which of them touched it. That question only has an answer against a real
    database — three of the five facts are the ``RETURNING`` of a statement, and
    two of those statements are deletes whose effect is invisible afterwards.

    The summaries are keyed by task id in these assertions so a test names the
    task it is about rather than an index into a list.
    """

    async def test_a_moved_due_anchor_is_reported_as_one(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=source_id,
        )

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == [
            TaskJournalRepointing(
                task_id=task_id, user_id=USER_ID, due_anchor_moved=True
            )
        ]

    async def test_a_moved_creating_anchor_is_reported_as_one(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The role has to be read *before* the update overwrites it.

        Both anchors end up holding the survivor's id, so afterwards there is
        nothing in the row to say which of them moved — which is why the
        pre-read carries the roles rather than the statement returning them.
        """
        target_id, source_id = merged_pair
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=due_id,
        )

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == [
            TaskJournalRepointing(
                task_id=task_id, user_id=USER_ID, creating_anchor_moved=True
            )
        ]

    async def test_a_task_anchored_in_both_roles_reports_both(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
    ):
        target_id, source_id = merged_pair
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=source_id,
        )

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == [
            TaskJournalRepointing(
                task_id=task_id,
                user_id=USER_ID,
                creating_anchor_moved=True,
                due_anchor_moved=True,
            )
        ]

    async def test_a_moved_link_is_reported_as_a_departure_and_an_arrival(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        await _link_intermediate(async_connection, task_id, source_id)

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == [
            TaskJournalRepointing(
                task_id=task_id,
                user_id=USER_ID,
                source_link_removed=True,
                target_link_added=True,
            )
        ]

    async def test_a_collapsed_duplicate_reports_only_the_departure(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The task was linked to both journals, so it gains nothing.

        Reporting an arrival here would put a second "linked" line in a history
        that already has one, for a link the user never gained — the failure the
        net-effect shape exists to prevent.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        await _link_intermediate(async_connection, task_id, source_id, target_id)

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == [
            TaskJournalRepointing(
                task_id=task_id, user_id=USER_ID, source_link_removed=True
            )
        ]
        # And the survivor's link is still there — which is *why* nothing was
        # gained. Asserted beside the report because the summary this produces
        # is identical to the move-then-drop case below, and the two are only
        # distinguishable by where they leave the task.
        assert await _intermediate_ids(async_connection, task_id) == [target_id]

    async def test_a_link_moved_and_then_dropped_reports_only_the_departure(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """Two statements cancel: the link arrives on the survivor and is deleted.

        The task's due anchor moves onto the survivor as well, so the
        redundancy cleanup removes the link it has just re-pointed. It never
        existed on the survivor between two committed states, so the summary
        must not claim it was gained.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=source_id,
        )
        await _link_intermediate(async_connection, task_id, source_id)

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == [
            TaskJournalRepointing(
                task_id=task_id,
                user_id=USER_ID,
                due_anchor_moved=True,
                source_link_removed=True,
            )
        ]
        # The other half of the pair: the same summary as the collapse above,
        # and the opposite end state. What the two share is the *change* — the
        # absorbed journal's link gone, none gained on the survivor — not where
        # the task is left, which differs because they started differently.
        assert await _intermediate_ids(async_connection, task_id) == []

    async def test_a_pre_existing_link_dropped_as_redundant_is_reported_as_lost(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The mirror direction: an anchor moves onto a journal already linked.

        The link the task loses is one it genuinely held before the merge, so
        this is the only one of the three link outcomes that reads as a removal
        of the *survivor*.
        """
        target_id, source_id = merged_pair
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=due_id,
        )
        await _link_intermediate(async_connection, task_id, target_id)

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == [
            TaskJournalRepointing(
                task_id=task_id,
                user_id=USER_ID,
                creating_anchor_moved=True,
                target_link_removed=True,
            )
        ]

    async def test_a_merge_touching_no_task_reports_nothing(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """Most merges are this one, and it must stay silent.

        A task exists and is untouched, so the emptiness is about the absorbed
        journal having no task on it rather than about there being no tasks at
        all — the control the assertion needs to mean anything.
        """
        target_id, source_id = merged_pair
        elsewhere_id = await create_journal(journal_repository, title="Elsewhere")
        await create_task(
            async_connection,
            creating_journal_id=elsewhere_id,
            due_journal_id=elsewhere_id,
        )

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert moved == []

    async def test_a_bystander_whose_link_survives_is_not_reported(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """The redundancy cleanup's scope, asserted through the report.

        A task holding an intermediate link to one of its own anchors is a shape
        retargeting produces without any merge, and the cleanup deliberately
        leaves it alone. If it did not, this bystander would appear here — which
        makes the report a second, independent check on that scoping.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        bystander_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=target_id,
            text="unrelated to the merge",
        )
        await _link_intermediate(async_connection, bystander_id, target_id)
        merged_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=target_id,
            text="the one the merge is about",
        )

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert [summary.task_id for summary in moved] == [merged_id]

    async def test_the_report_is_ordered_by_task_id(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """A total order, because the events are published in this order.

        Without it the two halves of the affected set — anchored tasks and
        linked ones — arrive in whatever order the union happens to produce, and
        one merge's outbox rows would be in a different order between runs.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        anchored_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=due_id,
            text="anchored to the absorbed journal",
        )
        linked_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="merely mentions it",
        )
        await _link_intermediate(async_connection, linked_id, source_id)

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=source_id, target_journal_id=target_id
        )

        assert [summary.task_id for summary in moved] == sorted(
            [anchored_id, linked_id]
        )

    async def test_repointing_a_journal_onto_itself_reports_nothing(
        self,
        task_anchor_repository: SqlTaskAnchorRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The early return still returns the empty report, not ``None``.

        No merge can reach this case, but the port promises it is a no-op and a
        caller publishing from the result would otherwise fail on the type.
        """
        journal_id = await create_journal(journal_repository, title="Only journal")
        other_id = await create_journal(journal_repository, title="Somewhere else")
        await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=other_id,
        )

        moved = await task_anchor_repository.repoint_journal_links(
            source_journal_id=journal_id, target_journal_id=journal_id
        )

        assert moved == []


@pytest.mark.integration
class TestTheMergeAndItsTaskEventsAreOneUnitOfWork:
    """A merge that fails leaves no task event behind it.

    The events are published from inside ``merge_journals``, which is
    ``@transactional`` and therefore joins a caller's unit of work rather than
    committing its own. So the failure staged here is the real one: a request
    handler that merges and then fails, which is also every merge that trips the
    cycle check or a foreign key after step 0.
    """

    async def test_a_rolled_back_merge_leaves_neither_the_move_nor_the_event(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """Both halves, because either one surviving alone is worse than neither.

        An outbox row without the move would put a change in the user's history
        that never happened to their task; the move without the row is the gap
        this phase exists to close, quietly reopened for one merge.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=source_id,
        )

        with pytest.raises(RuntimeError):
            async with unit_of_work(async_connection):
                await merge_service.merge_journals(
                    target_id, source_id, async_connection
                )
                raise RuntimeError("the caller failed after the journals were merged")

        assert (await _reload(task_repository, task_id)).due_journal_id == source_id
        assert await task_events(async_connection, task_id=task_id) == []


@pytest.mark.integration
class TestTheEventsGoOutInTheOrderTheWritesHappened:
    """A merge publishes about three aggregates; the order is not incidental.

    The relay hands events to the stream in ``(occurred_at, id)`` order, so it is
    the order a consumer rebuilding a timeline sees. The task events come first
    because the re-point is step 0 of the merge — which it is for a locking
    reason, not this one, but it does mean each event sits behind the write it
    announces rather than beside another's.
    """

    async def test_the_task_events_precede_the_merges_own_journal_events(
        self,
        merge_service: JournalMergeService,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=source_id,
        )

        await merge_service.merge_journals(target_id, source_id, async_connection)

        assert await _published_types(async_connection) == [
            "TaskJournalLinksRepointed",
            "JournalUpdated",
            "JournalDeleted",
        ]

    async def test_one_event_per_task_in_task_id_order(
        self,
        merge_service: JournalMergeService,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """Two tasks on the absorbed journal, and a total order over them.

        The repository reports in task-id order for this: without it the two
        halves of the affected set — anchored tasks and merely-linked ones —
        arrive in whatever order the plan produced, and one merge's stored events
        would be in a different order between runs.
        """
        target_id, source_id = merged_pair
        creating_id = await create_journal(journal_repository, title="Arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        anchored_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=due_id,
            text="anchored to the absorbed journal",
        )
        linked_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="merely mentions it",
        )
        await _link_intermediate(async_connection, linked_id, source_id)

        await merge_service.merge_journals(target_id, source_id, async_connection)

        events = await task_events(async_connection)
        assert [event.aggregate_id for event in events] == sorted(
            [anchored_id, linked_id]
        )


@pytest.mark.integration
class TestMergeBehaviourAroundTasks:
    """Everything merge already did, it still does with tasks in the picture."""

    async def test_children_tags_and_contacts_still_move(
        self,
        merge_service: JournalMergeService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        merged_pair: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ):
        """A merge carrying a task still re-parents, re-tags and re-links."""
        target_id, source_id = merged_pair
        task_id = await create_task(
            async_connection,
            creating_journal_id=source_id,
            due_journal_id=source_id,
        )

        child_id = await create_journal(journal_repository, title="A child")
        await async_connection.execute(
            text("UPDATE journals SET parent_id = :parent_id WHERE id = :id"),
            {"parent_id": source_id, "id": child_id},
        )
        tag_id = (
            await async_connection.execute(
                text(
                    "INSERT INTO journal_tags (user_id, name) VALUES ('test-user-123', 'trip') RETURNING id"
                )
            )
        ).scalar_one()
        await async_connection.execute(
            text(
                "INSERT INTO journal_tag_assignments (journal_id, tag_id) "
                "VALUES (:journal_id, :tag_id)"
            ),
            {"journal_id": source_id, "tag_id": tag_id},
        )
        contact_id = await create_contact(async_connection)
        await async_connection.execute(
            text(
                "INSERT INTO journal_contact_relationships "
                "(journal_id, contact_id, relationship_type) "
                "VALUES (:journal_id, :contact_id, 'PARTICIPANT')"
            ),
            {"journal_id": source_id, "contact_id": contact_id},
        )

        await merge_service.merge_journals(target_id, source_id, async_connection)

        reparented = await journal_repository.find_by_id(child_id)
        assert reparented is not None
        assert reparented.parent_id == target_id

        tags = await async_connection.execute(
            text("SELECT tag_id FROM journal_tag_assignments WHERE journal_id = :id"),
            {"id": target_id},
        )
        assert [row[0] for row in tags.fetchall()] == [tag_id]

        contacts = await async_connection.execute(
            text(
                "SELECT contact_id FROM journal_contact_relationships "
                "WHERE journal_id = :id"
            ),
            {"id": target_id},
        )
        assert [row[0] for row in contacts.fetchall()] == [contact_id]

        reloaded = await _reload(task_repository, task_id)
        assert reloaded.creating_journal_id == target_id
