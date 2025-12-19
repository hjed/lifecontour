"""Integration tests for JournalTagRepository."""

from uuid import uuid4

import pytest

from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag


@pytest.mark.integration
class TestJournalTagRepositoryIntegration:
    """Integration tests for journal tag repository."""

    @pytest.fixture
    async def tag_repo(self, async_connection):
        """Create a tag repository instance."""
        return SqlJournalTagRepository(async_connection)

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
        tag = JournalTag(name="work", color="#FF0000")
        saved_tag = await tag_repo.save(tag)

        saved_tag.color = "#00FF00"
        updated_tag = await tag_repo.save(saved_tag)

        assert updated_tag.color == "#00FF00"
        assert updated_tag.updated_at > saved_tag.created_at

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
