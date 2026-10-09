"""Integration tests for JournalTagRepository."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag


@pytest_asyncio.fixture
async def tag_repo(async_connection: AsyncConnection) -> SqlJournalTagRepository:
    """Create a tag repository instance."""
    return SqlJournalTagRepository(async_connection)


async def _create_journal(connection: AsyncConnection, title: str) -> int:
    """Insert a second journal alongside the shared ``sample_journal_id``.

    Only the columns the assignment FK needs are populated: these tests are about
    the junction table, not journal content.
    """
    now = datetime.now(UTC)
    result = await connection.execute(
        text(
            """
            INSERT INTO journals
                (user_id, title, content,
                 event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
            """
        ),
        {
            "user_id": "test-user-123",
            "title": title,
            "content": "Tag fan-out subject",
            "start": now,
            "end": now,
        },
    )
    row = result.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.integration
class TestJournalTagRepositoryIntegration:
    """Integration tests for journal tag repository."""

    async def test_save_new_tag(self, tag_repo):
        """Test saving a new tag."""
        tag = JournalTag(name="work")
        saved_tag = await tag_repo.save(tag)

        assert saved_tag.id is not None
        assert saved_tag.name == "work"
        assert saved_tag.created_at is not None
        assert saved_tag.updated_at is not None

    async def test_save_persists_the_owner_and_find_returns_it(self, tag_repo):
        saved_tag = await tag_repo.save(JournalTag(name="owned", user_id="owner-1"))

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is not None
        assert found_tag.user_id == "owner-1"

    async def test_an_update_never_re_owns_a_tag(self, tag_repo):
        """The owner is written on INSERT only."""
        saved_tag = await tag_repo.save(JournalTag(name="owned", user_id="owner-1"))
        saved_tag.user_id = "someone-else"
        saved_tag.color = "#123456"
        await tag_repo.save(saved_tag)

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is not None
        assert found_tag.color == "#123456"
        assert found_tag.user_id == "owner-1"

    async def test_find_tag_by_id(self, tag_repo):
        """Test finding a tag by ID."""
        tag = JournalTag(name="work")
        saved_tag = await tag_repo.save(tag)

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is not None
        assert found_tag.name == "work"
        assert found_tag.id == saved_tag.id

    async def test_find_tag_by_name(self, tag_repo):
        """Test finding a tag by name."""
        tag = JournalTag(name="work")
        await tag_repo.save(tag)

        found_tag = await tag_repo.find_by_name("work")
        assert found_tag is not None
        assert found_tag.name == "work"

    async def test_find_nonexistent_tag_returns_none(self, tag_repo):
        """Test finding nonexistent tag returns None."""
        found_tag = await tag_repo.find_by_id(uuid4())
        assert found_tag is None

    async def test_update_tag(self, tag_repo):
        """Test updating a tag."""
        import asyncio

        tag = JournalTag(name="work", color="#FF0000")
        saved_tag = await tag_repo.save(tag)

        # Add a small delay to ensure updated_at is different from created_at
        await asyncio.sleep(0.01)

        saved_tag.color = "#00FF00"
        updated_tag = await tag_repo.save(saved_tag)

        assert updated_tag.color == "#00FF00"
        assert updated_tag.updated_at >= saved_tag.created_at

    async def test_save_and_find_tag_with_description(self, tag_repo):
        """Test description round-trips through insert and find_by_id."""
        tag = JournalTag(
            name="work",
            color="#FF0000",
            description="Work-related journal entries",
        )
        saved_tag = await tag_repo.save(tag)

        assert saved_tag.description == "Work-related journal entries"

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is not None
        assert found_tag.description == "Work-related journal entries"

    async def test_save_tag_without_description_stores_null(self, tag_repo):
        """Test description is nullable, so tags may omit it."""
        saved_tag = await tag_repo.save(JournalTag(name="work"))

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is not None
        assert found_tag.description is None

    async def test_update_tag_description(self, tag_repo):
        """Test the update path persists a changed description."""
        saved_tag = await tag_repo.save(
            JournalTag(name="work", description="Original text")
        )

        saved_tag.description = "Revised text"
        await tag_repo.save(saved_tag)

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is not None
        assert found_tag.description == "Revised text"

    async def test_update_tag_reparent_persists(self, tag_repo):
        """Test the update path persists a changed parent, including clearing it."""
        parent = await tag_repo.save(JournalTag(name="outdoors"))
        child = await tag_repo.save(JournalTag(name="climbing"))

        child.parent_id = parent.id
        await tag_repo.save(child)
        reparented = await tag_repo.find_by_id(child.id)
        assert reparented is not None
        assert reparented.parent_id == parent.id

        reparented.parent_id = None
        await tag_repo.save(reparented)
        cleared = await tag_repo.find_by_id(child.id)
        assert cleared is not None
        assert cleared.parent_id is None

    async def test_find_by_name_is_case_insensitive(self, tag_repo):
        """Test the uniqueness lookup matches regardless of case."""
        await tag_repo.save(JournalTag(name="Training"))

        assert await tag_repo.find_by_name("training") is not None
        assert await tag_repo.find_by_name("TRAINING") is not None

    async def test_find_by_name_returns_description(self, tag_repo):
        """Test find_by_name selects the description column."""
        await tag_repo.save(JournalTag(name="work", description="Work entries"))

        found_tag = await tag_repo.find_by_name("work")
        assert found_tag is not None
        assert found_tag.description == "Work entries"

    async def test_get_all_returns_description(self, tag_repo):
        """Test get_all selects the description column."""
        await tag_repo.save(JournalTag(name="work", description="Work entries"))

        tags = await tag_repo.get_all()
        assert [t.description for t in tags] == ["Work entries"]

    async def test_get_root_tags_returns_description(self, tag_repo):
        """Test get_root_tags selects the description column."""
        await tag_repo.save(JournalTag(name="work", description="Work entries"))

        tags = await tag_repo.get_root_tags()
        assert [t.description for t in tags] == ["Work entries"]

    async def test_get_children_returns_description(self, tag_repo):
        """Test get_children selects the description column."""
        parent = await tag_repo.save(JournalTag(name="work"))
        await tag_repo.save(
            JournalTag(
                name="work-meetings", parent_id=parent.id, description="Standups"
            )
        )

        children = await tag_repo.get_children(parent.id)
        assert [t.description for t in children] == ["Standups"]

    async def test_delete_tag(self, tag_repo):
        """Test deleting a tag."""
        tag = JournalTag(name="work")
        saved_tag = await tag_repo.save(tag)

        await tag_repo.delete(saved_tag.id)

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is None

    async def test_get_all_tags(self, tag_repo):
        """Test getting all tags."""
        tag1 = JournalTag(name="work")
        tag2 = JournalTag(name="personal")
        await tag_repo.save(tag1)
        await tag_repo.save(tag2)

        all_tags = await tag_repo.get_all()
        assert len(all_tags) >= 2
        names = [tag.name for tag in all_tags]
        assert "work" in names
        assert "personal" in names

    async def test_get_root_tags(self, tag_repo):
        """Test getting root tags (no parent)."""
        root_tag = JournalTag(name="root")
        saved_root = await tag_repo.save(root_tag)

        child_tag = JournalTag(name="child", parent_id=saved_root.id)
        await tag_repo.save(child_tag)

        root_tags = await tag_repo.get_root_tags()
        root_names = [tag.name for tag in root_tags]
        assert "root" in root_names
        assert "child" not in root_names

    async def test_get_children(self, tag_repo):
        """Test getting child tags."""
        parent_tag = JournalTag(name="parent")
        saved_parent = await tag_repo.save(parent_tag)

        child1 = JournalTag(name="child1", parent_id=saved_parent.id)
        child2 = JournalTag(name="child2", parent_id=saved_parent.id)
        await tag_repo.save(child1)
        await tag_repo.save(child2)

        children = await tag_repo.get_children(saved_parent.id)
        assert len(children) == 2
        child_names = [tag.name for tag in children]
        assert "child1" in child_names
        assert "child2" in child_names

    async def test_tag_hierarchy(self, tag_repo):
        """Test tag hierarchy with multiple levels."""
        root = JournalTag(name="root")
        saved_root = await tag_repo.save(root)

        level1 = JournalTag(name="level1", parent_id=saved_root.id)
        saved_level1 = await tag_repo.save(level1)

        level2 = JournalTag(name="level2", parent_id=saved_level1.id)
        await tag_repo.save(level2)

        # Check root has one child
        root_children = await tag_repo.get_children(saved_root.id)
        assert len(root_children) == 1

        # Check level1 has one child
        level1_children = await tag_repo.get_children(saved_level1.id)
        assert len(level1_children) == 1

    async def test_tag_with_color(self, tag_repo):
        """Test saving and retrieving tag with color."""
        tag = JournalTag(name="important", color="#FF0000")
        saved_tag = await tag_repo.save(tag)

        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag.color == "#FF0000"

    async def test_delete_cascades_assignments(self, tag_repo, async_connection):
        """Test deleting a tag removes its journal assignments via ON DELETE CASCADE.

        This is what makes delete parity safe: the service does not have to
        un-assign the tag by hand before deleting it.
        """
        from core_shared.models.journals import EventDateRange, Journal
        from sqlalchemy import text

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        journal_repo = SqlJournalRepository(async_connection)
        saved_journal = await journal_repo.save(
            Journal(
                user_id="test-user",
                title="Tagged Journal",
                content="Test content",
                event_date_range=EventDateRange(
                    start=datetime.now(UTC), end=datetime.now(UTC)
                ),
            )
        )
        saved_tag = await tag_repo.save(JournalTag(name="doomed"))
        await tag_repo.assign_tag(saved_journal.id, saved_tag.id)

        await tag_repo.delete(saved_tag.id)

        result = await async_connection.execute(
            text("SELECT COUNT(*) FROM journal_tag_assignments WHERE tag_id = :tag_id"),
            {"tag_id": saved_tag.id},
        )
        assert result.scalar() == 0
        assert await tag_repo.get_tags_for_journal(saved_journal.id) == []

    async def test_delete_sets_child_parent_id_null(self, tag_repo):
        """Test deleting a parent tag re-parents its children to NULL."""
        parent = await tag_repo.save(JournalTag(name="outdoors"))
        child = await tag_repo.save(JournalTag(name="climbing", parent_id=parent.id))

        await tag_repo.delete(parent.id)

        surviving_child = await tag_repo.find_by_id(child.id)
        assert surviving_child is not None
        assert surviving_child.parent_id is None

    @staticmethod
    async def _save_journal(async_connection, title: str):
        """Persist a minimal journal to hang tag assignments off."""
        from core_shared.models.journals import EventDateRange, Journal

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        journal_repo = SqlJournalRepository(async_connection)
        return await journal_repo.save(
            Journal(
                user_id="test-user",
                title=title,
                content="Test content",
                event_date_range=EventDateRange(
                    start=datetime.now(UTC), end=datetime.now(UTC)
                ),
            )
        )

    async def test_merge_into_repoints_assignments(self, tag_repo, async_connection):
        """Test merging moves the source tag's assignments onto the target."""
        journal = await self._save_journal(async_connection, "Hike")
        source = await tag_repo.save(JournalTag(name="hiking"))
        target = await tag_repo.save(JournalTag(name="bushwalking"))
        await tag_repo.assign_tag(journal.id, source.id)

        await tag_repo.merge_into(source.id, target.id)

        tag_ids = {tag.id for tag in await tag_repo.get_tags_for_journal(journal.id)}
        assert tag_ids == {target.id}

    async def test_merge_into_dedupes_overlapping_assignments(
        self, tag_repo, async_connection
    ):
        """Test a journal holding both tags ends up with a single assignment.

        A naive ``UPDATE ... SET tag_id`` would violate the composite primary
        key on ``journal_tag_assignments`` here, so this is the case that
        proves the pre-delete step is doing its job.
        """
        from sqlalchemy import text

        journal = await self._save_journal(async_connection, "Both tags")
        source = await tag_repo.save(JournalTag(name="hiking"))
        target = await tag_repo.save(JournalTag(name="bushwalking"))
        await tag_repo.assign_tag(journal.id, source.id)
        await tag_repo.assign_tag(journal.id, target.id)

        await tag_repo.merge_into(source.id, target.id)

        result = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM journal_tag_assignments "
                "WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal.id},
        )
        assert result.scalar() == 1
        tag_ids = {tag.id for tag in await tag_repo.get_tags_for_journal(journal.id)}
        assert tag_ids == {target.id}

    async def test_merge_into_reparents_children_to_target(self, tag_repo):
        """Test the source's children are adopted by the target, not orphaned."""
        source = await tag_repo.save(JournalTag(name="hiking"))
        target = await tag_repo.save(JournalTag(name="bushwalking"))
        child = await tag_repo.save(JournalTag(name="day walks", parent_id=source.id))

        await tag_repo.merge_into(source.id, target.id)

        surviving_child = await tag_repo.find_by_id(child.id)
        assert surviving_child is not None
        assert surviving_child.parent_id == target.id

    async def test_merge_into_target_that_is_a_child_of_source(self, tag_repo):
        """Test merging a tag into its own child does not self-parent the target.

        The service rejects this combination, but the repository must not be
        able to write a self-cycle if a future caller reaches it directly — a
        tag that is its own parent would poison every later ancestry walk.
        """
        source = await tag_repo.save(JournalTag(name="outdoors"))
        target = await tag_repo.save(JournalTag(name="climbing", parent_id=source.id))
        sibling = await tag_repo.save(JournalTag(name="hiking", parent_id=source.id))

        await tag_repo.merge_into(source.id, target.id)

        surviving_target = await tag_repo.find_by_id(target.id)
        assert surviving_target is not None
        assert surviving_target.parent_id is None, (
            "the target must not become its own parent"
        )
        # The genuine sibling is still adopted by the target.
        surviving_sibling = await tag_repo.find_by_id(sibling.id)
        assert surviving_sibling is not None
        assert surviving_sibling.parent_id == target.id

    async def test_merge_into_self_is_rejected(self, tag_repo, async_connection):
        """Test merging a tag into itself is refused rather than deleting it.

        Without the guard the dedupe step matches every assignment against
        itself, so the tag would lose all its assignments and then be deleted —
        silent data loss from a call that reads like a no-op. The service
        rejects this first; this pins the repository's own contract.
        """
        journal = await self._save_journal(async_connection, "Kept")
        tag = await tag_repo.save(JournalTag(name="hiking"))
        await tag_repo.assign_tag(journal.id, tag.id)

        with pytest.raises(ValueError, match="distinct source and target"):
            await tag_repo.merge_into(tag.id, tag.id)

        assert await tag_repo.find_by_id(tag.id) is not None
        assert [t.id for t in await tag_repo.get_tags_for_journal(journal.id)] == [
            tag.id
        ]

    async def test_merge_into_deletes_source_tag(self, tag_repo):
        """Test the source tag is gone after the merge and the target survives."""
        source = await tag_repo.save(JournalTag(name="hiking"))
        target = await tag_repo.save(JournalTag(name="bushwalking"))

        await tag_repo.merge_into(source.id, target.id)

        assert await tag_repo.find_by_id(source.id) is None
        assert await tag_repo.find_by_id(target.id) is not None

    async def test_get_tags_for_journal(self, tag_repo, async_connection):
        """Test getting tags assigned to a journal."""
        from core_shared.models.journals import EventDateRange, Journal
        from sqlalchemy import text

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        # Create a journal
        journal_repo = SqlJournalRepository(async_connection)
        journal = Journal(
            user_id="test-user",
            title="Test Journal",
            content="Test content",
            event_date_range=EventDateRange(
                start=datetime.now(UTC), end=datetime.now(UTC)
            ),
        )
        saved_journal = await journal_repo.save(journal)

        # Create tags
        tag1 = JournalTag(name="work")
        tag2 = JournalTag(name="personal")
        saved_tag1 = await tag_repo.save(tag1)
        saved_tag2 = await tag_repo.save(tag2)

        # Assign tags to journal
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_tag_assignments (journal_id, tag_id)
                VALUES (:journal_id, :tag_id)
            """
            ),
            {"journal_id": saved_journal.id, "tag_id": saved_tag1.id},
        )
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_tag_assignments (journal_id, tag_id)
                VALUES (:journal_id, :tag_id)
            """
            ),
            {"journal_id": saved_journal.id, "tag_id": saved_tag2.id},
        )

        # Get tags for journal
        tags = await tag_repo.get_tags_for_journal(saved_journal.id)
        assert len(tags) == 2
        tag_names = [tag.name for tag in tags]
        assert "work" in tag_names
        assert "personal" in tag_names

    async def test_get_tags_for_journal_returns_description(
        self, tag_repo, async_connection
    ):
        """Test get_tags_for_journal selects the description column."""
        from core_shared.models.journals import EventDateRange, Journal

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        journal_repo = SqlJournalRepository(async_connection)
        saved_journal = await journal_repo.save(
            Journal(
                user_id="test-user",
                title="Test Journal",
                content="Test content",
                event_date_range=EventDateRange(
                    start=datetime.now(UTC), end=datetime.now(UTC)
                ),
            )
        )

        saved_tag = await tag_repo.save(
            JournalTag(name="work", description="Work entries")
        )
        await tag_repo.assign_tag(saved_journal.id, saved_tag.id)

        tags = await tag_repo.get_tags_for_journal(saved_journal.id)
        assert [t.description for t in tags] == ["Work entries"]

    async def test_assign_tag_to_journal(self, tag_repo, async_connection):
        """Test assigning a tag to a journal using the repository method."""
        from core_shared.models.journals import EventDateRange, Journal

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        # Create a journal
        journal_repo = SqlJournalRepository(async_connection)
        journal = Journal(
            user_id="test-user",
            title="Test Journal",
            content="Test content",
            event_date_range=EventDateRange(
                start=datetime.now(UTC), end=datetime.now(UTC)
            ),
        )
        saved_journal = await journal_repo.save(journal)

        # Create a tag
        tag = JournalTag(name="work")
        saved_tag = await tag_repo.save(tag)

        # Assign tag to journal
        await tag_repo.assign_tag(saved_journal.id, saved_tag.id)

        # Verify tag was assigned
        tags = await tag_repo.get_tags_for_journal(saved_journal.id)
        assert len(tags) == 1
        assert tags[0].name == "work"

    async def test_remove_tag_from_journal(self, tag_repo, async_connection):
        """Test removing a tag from a journal using the repository method."""
        from core_shared.models.journals import EventDateRange, Journal
        from sqlalchemy import text

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        # Create a journal
        journal_repo = SqlJournalRepository(async_connection)
        journal = Journal(
            user_id="test-user",
            title="Test Journal",
            content="Test content",
            event_date_range=EventDateRange(
                start=datetime.now(UTC), end=datetime.now(UTC)
            ),
        )
        saved_journal = await journal_repo.save(journal)

        # Create tags
        tag1 = JournalTag(name="work")
        tag2 = JournalTag(name="personal")
        saved_tag1 = await tag_repo.save(tag1)
        saved_tag2 = await tag_repo.save(tag2)

        # Assign tags to journal
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_tag_assignments (journal_id, tag_id)
                VALUES (:journal_id, :tag_id)
            """
            ),
            {"journal_id": saved_journal.id, "tag_id": saved_tag1.id},
        )
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_tag_assignments (journal_id, tag_id)
                VALUES (:journal_id, :tag_id)
            """
            ),
            {"journal_id": saved_journal.id, "tag_id": saved_tag2.id},
        )

        # Remove one tag
        await tag_repo.remove_tag(saved_journal.id, saved_tag1.id)

        # Verify only one tag remains
        tags = await tag_repo.get_tags_for_journal(saved_journal.id)
        assert len(tags) == 1
        assert tags[0].name == "personal"


@pytest.mark.integration
class TestAssignmentChangeReporting:
    """assign_tag / remove_tag report whether the junction table changed.

    The tag service publishes ``JournalTagAssigned`` / ``JournalTagRemoved`` only
    on a real change, so these booleans are what keeps the activity feed free of
    entries for operations that changed nothing. Asserted against real SQL because
    both answers come from Postgres (``RETURNING`` under ``DO NOTHING``, and
    ``rowcount``) rather than from application logic.
    """

    async def test_assign_tag_reports_new_then_duplicate(
        self, tag_repo, sample_journal_id
    ):
        tag = await tag_repo.save(JournalTag(name="assign-reporting"))

        assert await tag_repo.assign_tag(sample_journal_id, tag.id) is True
        assert await tag_repo.assign_tag(sample_journal_id, tag.id) is False

        # The repeat must not have created a second row either.
        assert len(await tag_repo.get_tags_for_journal(sample_journal_id)) == 1

    async def test_remove_tag_reports_deleted_then_absent(
        self, tag_repo, sample_journal_id
    ):
        tag = await tag_repo.save(JournalTag(name="remove-reporting"))
        await tag_repo.assign_tag(sample_journal_id, tag.id)

        assert await tag_repo.remove_tag(sample_journal_id, tag.id) is True
        assert await tag_repo.remove_tag(sample_journal_id, tag.id) is False

    async def test_remove_tag_reports_absent_when_never_assigned(
        self, tag_repo, sample_journal_id
    ):
        tag = await tag_repo.save(JournalTag(name="never-assigned"))

        assert await tag_repo.remove_tag(sample_journal_id, tag.id) is False


@pytest.mark.integration
class TestGetJournalIdsForTag:
    """The reverse lookup that tag-scoped writes fan their events out over.

    A rename publishes one journal-scoped event per journal carrying the tag, so
    a query that under-reports would silently lose those journals' history
    entries. Asserted against real assignment rows rather than a mock.
    """

    async def test_returns_every_journal_carrying_the_tag(
        self, tag_repo, async_connection, sample_journal_id
    ):
        second_journal_id = await _create_journal(async_connection, "Second subject")
        tag = await tag_repo.save(JournalTag(name="fan-out"))
        await tag_repo.assign_tag(sample_journal_id, tag.id)
        await tag_repo.assign_tag(second_journal_id, tag.id)

        journal_ids = await tag_repo.get_journal_ids_for_tag(tag.id)

        assert journal_ids == sorted([sample_journal_id, second_journal_id])

    async def test_excludes_journals_carrying_a_different_tag(
        self, tag_repo, async_connection, sample_journal_id
    ):
        other_journal_id = await _create_journal(async_connection, "Other subject")
        tag = await tag_repo.save(JournalTag(name="wanted"))
        other_tag = await tag_repo.save(JournalTag(name="unwanted"))
        await tag_repo.assign_tag(sample_journal_id, tag.id)
        await tag_repo.assign_tag(other_journal_id, other_tag.id)

        assert await tag_repo.get_journal_ids_for_tag(tag.id) == [sample_journal_id]

    async def test_returns_empty_for_an_unassigned_tag(self, tag_repo):
        tag = await tag_repo.save(JournalTag(name="unassigned"))

        assert await tag_repo.get_journal_ids_for_tag(tag.id) == []

    async def test_returns_empty_for_an_unknown_tag(self, tag_repo):
        """An unknown id is indistinguishable from an unassigned one here."""
        assert await tag_repo.get_journal_ids_for_tag(uuid4()) == []

    async def test_reflects_a_removed_assignment(self, tag_repo, sample_journal_id):
        """Un-assigning must drop the journal, or a rename would over-report."""
        tag = await tag_repo.save(JournalTag(name="transient"))
        await tag_repo.assign_tag(sample_journal_id, tag.id)
        await tag_repo.remove_tag(sample_journal_id, tag.id)

        assert await tag_repo.get_journal_ids_for_tag(tag.id) == []


@pytest.mark.integration
class TestGetDescendantsForTags:
    """Recursive descendant lookup backing hierarchical journal tag filtering."""

    async def test_returns_all_levels_of_descendants(self, tag_repo):
        parent = await tag_repo.save(JournalTag(name="outdoors"))
        child = await tag_repo.save(JournalTag(name="climbing", parent_id=parent.id))
        grandchild = await tag_repo.save(
            JournalTag(name="sport-climbing", parent_id=child.id)
        )

        descendants = await tag_repo.get_descendants_for_tags([parent.id])

        assert {tag.id for tag in descendants} == {child.id, grandchild.id}

    async def test_handles_multiple_roots_in_one_call(self, tag_repo):
        first_root = await tag_repo.save(JournalTag(name="work"))
        first_child = await tag_repo.save(
            JournalTag(name="work-meetings", parent_id=first_root.id)
        )
        second_root = await tag_repo.save(JournalTag(name="personal"))
        second_child = await tag_repo.save(
            JournalTag(name="personal-health", parent_id=second_root.id)
        )

        descendants = await tag_repo.get_descendants_for_tags(
            [first_root.id, second_root.id]
        )

        assert {tag.id for tag in descendants} == {first_child.id, second_child.id}

    async def test_leaf_tag_has_no_descendants(self, tag_repo):
        parent = await tag_repo.save(JournalTag(name="outdoors"))
        leaf = await tag_repo.save(JournalTag(name="climbing", parent_id=parent.id))

        assert await tag_repo.get_descendants_for_tags([leaf.id]) == []

    async def test_empty_input_returns_empty_list(self, tag_repo):
        await tag_repo.save(JournalTag(name="outdoors"))

        assert await tag_repo.get_descendants_for_tags([]) == []

    async def test_excludes_ancestors_and_unrelated_tags(self, tag_repo):
        parent = await tag_repo.save(JournalTag(name="outdoors"))
        child = await tag_repo.save(JournalTag(name="climbing", parent_id=parent.id))
        await tag_repo.save(JournalTag(name="unrelated"))

        descendants = await tag_repo.get_descendants_for_tags([child.id])

        assert descendants == []

    async def test_maps_full_tag_row(self, tag_repo):
        parent = await tag_repo.save(JournalTag(name="outdoors"))
        child = await tag_repo.save(
            JournalTag(
                name="climbing",
                parent_id=parent.id,
                color="#FF0000",
                description="Rock climbing entries",
            )
        )

        descendants = await tag_repo.get_descendants_for_tags([parent.id])

        assert len(descendants) == 1
        assert descendants[0].id == child.id
        assert descendants[0].name == "climbing"
        assert descendants[0].parent_id == parent.id
        assert descendants[0].color == "#FF0000"
        assert descendants[0].description == "Rock climbing entries"
        assert descendants[0].created_at is not None
