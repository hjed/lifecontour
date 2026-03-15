"""Integration tests for TagRepository with real database."""

import pytest
from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlTagRepository
from app.core.contacts.models.exceptions import DuplicateTagNameError, TagNotFoundError


@pytest.mark.integration
class TestTagRepositoryIntegration:
    """Integration tests for TagRepository with real database."""

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection):
        """Create TagRepository instance with real database connection."""
        return SqlTagRepository(clean_database)

    @pytest.mark.asyncio
    async def test_save_new_tag(self, tag_repo):
        """Test saving a new tag to database."""
        # Arrange
        tag = Tag(
            name=TagName("work"), color="#FF0000", description="Work-related contacts"
        )

        # Act
        saved_tag = await tag_repo.save(tag)

        # Assert
        assert saved_tag.id is not None
        assert str(saved_tag.name) == "work"
        assert saved_tag.color == "#FF0000"
        assert saved_tag.description == "Work-related contacts"
        assert saved_tag.created_at is not None
        assert saved_tag.updated_at is not None

    @pytest.mark.asyncio
    async def test_save_update_existing_tag(self, tag_repo):
        """Test updating an existing tag in database."""
        # Arrange - Create tag
        tag = Tag(name=TagName("work"), color="#FF0000")
        saved_tag = await tag_repo.save(tag)

        # Update tag
        saved_tag.color = "#00FF00"
        saved_tag.description = "Updated description"

        # Act
        updated_tag = await tag_repo.save(saved_tag)

        # Assert
        assert updated_tag.id == saved_tag.id
        assert str(updated_tag.name) == "work"
        assert updated_tag.color == "#00FF00"
        assert updated_tag.description == "Updated description"
        assert updated_tag.updated_at is not None

        # Verify the tag was actually updated in the database
        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag.color == "#00FF00"
        assert found_tag.description == "Updated description"

    @pytest.mark.asyncio
    async def test_save_duplicate_name_raises_error(self, tag_repo):
        """Test saving tag with duplicate name raises error."""
        # Arrange - Create first tag
        tag1 = Tag(name=TagName("work"))
        await tag_repo.save(tag1)

        # Try to create second tag with same name
        tag2 = Tag(name=TagName("work"))

        # Act & Assert
        with pytest.raises(DuplicateTagNameError):
            await tag_repo.save(tag2)

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, tag_repo):
        """Test finding tag by ID when it exists."""
        # Arrange
        tag = Tag(name=TagName("personal"), color="#0000FF")
        saved_tag = await tag_repo.save(tag)

        # Act
        found_tag = await tag_repo.find_by_id(saved_tag.id)

        # Assert
        assert found_tag is not None
        assert found_tag.id == saved_tag.id
        assert str(found_tag.name) == "personal"
        assert found_tag.color == "#0000FF"

    @pytest.mark.asyncio
    async def test_find_by_id_not_existing(self, tag_repo):
        """Test finding tag by ID when it doesn't exist."""
        # Act
        found_tag = await tag_repo.find_by_id(999)

        # Assert
        assert found_tag is None

    @pytest.mark.asyncio
    async def test_find_by_name_existing(self, tag_repo):
        """Test finding tag by name when it exists."""
        # Arrange
        tag = Tag(name=TagName("client"), color="#FFFF00")
        saved_tag = await tag_repo.save(tag)

        # Act
        found_tag = await tag_repo.find_by_name("client")

        # Assert
        assert found_tag is not None
        assert found_tag.id == saved_tag.id
        assert str(found_tag.name) == "client"
        assert found_tag.color == "#FFFF00"

    @pytest.mark.asyncio
    async def test_find_by_name_not_existing(self, tag_repo):
        """Test finding tag by name when it doesn't exist."""
        # Act
        found_tag = await tag_repo.find_by_name("nonexistent")

        # Assert
        assert found_tag is None

    @pytest.mark.asyncio
    async def test_find_by_names(self, tag_repo):
        """Test finding multiple tags by name."""
        # Arrange
        tag1 = Tag(name=TagName("tag_a"))
        tag2 = Tag(name=TagName("tag_b"))
        tag3 = Tag(name=TagName("tag_c"))
        await tag_repo.save(tag1)
        await tag_repo.save(tag2)
        await tag_repo.save(tag3)

        # Act
        results = await tag_repo.find_by_names(["tag_a", "tag_c", "nonexistent"])

        # Assert
        assert len(results) == 2
        assert "tag_a" in results
        assert "tag_c" in results
        assert "nonexistent" not in results
        assert str(results["tag_a"].name) == "tag_a"
        assert str(results["tag_c"].name) == "tag_c"

    @pytest.mark.asyncio
    async def test_find_by_names_empty_list(self, tag_repo):
        """Test finding tags with an empty list of names."""
        # Act
        results = await tag_repo.find_by_names([])

        # Assert
        assert isinstance(results, dict)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_all_tags(self, tag_repo):
        """Test getting all tags."""
        # Arrange - Create multiple tags
        tag1 = Tag(name=TagName("work"))
        tag2 = Tag(name=TagName("personal"))
        tag3 = Tag(name=TagName("client"))

        await tag_repo.save(tag1)
        await tag_repo.save(tag2)
        await tag_repo.save(tag3)

        # Act
        all_tags = await tag_repo.get_all()

        # Assert
        assert len(all_tags) >= 3
        tag_names = [str(tag.name) for tag in all_tags]
        assert "work" in tag_names
        assert "personal" in tag_names
        assert "client" in tag_names

    @pytest.mark.asyncio
    async def test_delete_tag(self, tag_repo):
        """Test deleting a tag."""
        # Arrange
        tag = Tag(name=TagName("temporary"))
        saved_tag = await tag_repo.save(tag)

        # Act
        await tag_repo.delete(saved_tag.id)

        # Assert - Tag should no longer exist
        found_tag = await tag_repo.find_by_id(saved_tag.id)
        assert found_tag is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_tag_raises_error(self, tag_repo):
        """Test deleting non-existent tag raises error."""
        # Act & Assert
        with pytest.raises(TagNotFoundError):
            await tag_repo.delete(999)

    @pytest.mark.asyncio
    async def test_hierarchical_tags(self, tag_repo):
        """Test creating hierarchical tags with parent-child relationships."""
        # Arrange - Create parent tag
        parent_tag = Tag(name=TagName("business"))
        saved_parent = await tag_repo.save(parent_tag)

        # Create child tag
        child_tag = Tag(name=TagName("client"), parent_id=saved_parent.id)

        # Act
        saved_child = await tag_repo.save(child_tag)

        # Assert
        assert saved_child.id is not None
        assert saved_child.parent_id == saved_parent.id
        assert str(saved_child.name) == "client"

        # Verify parent can be found
        found_parent = await tag_repo.find_by_id(saved_parent.id)
        assert found_parent is not None
        assert str(found_parent.name) == "business"

    @pytest.mark.asyncio
    async def test_search_tags(self, tag_repo):
        """Test searching tags by name pattern."""
        # Arrange - Create tags with similar names
        tag1 = Tag(name=TagName("work-project"))
        tag2 = Tag(name=TagName("work-meeting"))
        tag3 = Tag(name=TagName("personal"))

        await tag_repo.save(tag1)
        await tag_repo.save(tag2)
        await tag_repo.save(tag3)

        # Act
        results = await tag_repo.search("work")

        # Assert
        assert len(results) >= 2
        tag_names = [str(tag.name) for tag in results]
        assert any("work" in name for name in tag_names)

    @pytest.mark.asyncio
    async def test_get_tags_by_parent(self, tag_repo):
        """Test getting tags by parent ID."""
        # Arrange - Create parent and child tags
        parent_tag = Tag(name=TagName("categories"))
        saved_parent = await tag_repo.save(parent_tag)

        child1 = Tag(name=TagName("work"), parent_id=saved_parent.id)
        child2 = Tag(name=TagName("personal"), parent_id=saved_parent.id)
        orphan = Tag(name=TagName("orphan"))  # No parent

        await tag_repo.save(child1)
        await tag_repo.save(child2)
        await tag_repo.save(orphan)

        # Act
        children = await tag_repo.get_children(saved_parent.id)

        # Assert
        assert len(children) == 2
        child_names = [str(tag.name) for tag in children]
        assert "work" in child_names
        assert "personal" in child_names
        assert "orphan" not in child_names

    @pytest.mark.asyncio
    async def test_get_root_tags(self, tag_repo):
        """Test getting root tags (tags without parents)."""
        # Arrange - Create mix of root and child tags
        root1 = Tag(name=TagName("root1"))
        root2 = Tag(name=TagName("root2"))
        saved_root1 = await tag_repo.save(root1)
        await tag_repo.save(root2)  # Save but don't need to store reference

        child = Tag(name=TagName("child"), parent_id=saved_root1.id)
        await tag_repo.save(child)

        # Act
        root_tags = await tag_repo.get_root_tags()

        # Assert
        assert len(root_tags) >= 2
        root_names = [str(tag.name) for tag in root_tags]
        assert "root1" in root_names
        assert "root2" in root_names
        assert "child" not in root_names
