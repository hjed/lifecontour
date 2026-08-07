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
from core_shared.models.tasks import Task, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_contact,
    create_journal,
    create_task,
    link_intermediate_journal,
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
async def merge_service(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    task_anchor_repository: SqlTaskAnchorRepository,
) -> JournalMergeService:
    return JournalMergeService(
        journal_repo=journal_repository,
        event_publisher=OutboxEventPublisher(async_connection),
        task_anchor_repo=task_anchor_repository,
    )


@pytest_asyncio.fixture
async def merged_pair(journal_repository: SqlJournalRepository) -> tuple[int, int]:
    """The survivor and the journal absorbed into it, as ``(target, source)``."""
    target_id = await create_journal(journal_repository, title="Survivor")
    source_id = await create_journal(journal_repository, title="Absorbed")
    return target_id, source_id


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
                text("INSERT INTO journal_tags (name) VALUES ('trip') RETURNING id")
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
