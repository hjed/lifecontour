"""Integration tests for JournalTagRepository."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag


@pytest_asyncio.fixture
async def tag_repo(async_connection: AsyncConnection) -> SqlJournalTagRepository:
    """Create a tag repository instance."""
    return SqlJournalTagRepository(async_connection)


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
