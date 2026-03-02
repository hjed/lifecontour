"""Tests for TagHierarchyService."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.value_objects import TagName

from app.core.contacts.models.exceptions import (
    DuplicateTagNameError,
    TagNotFoundError,
)
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService


class TestTagHierarchyService:
    """Test TagHierarchyService."""

    @pytest.fixture
    def mock_tag_repo(self):
        """Create mock tag repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_transaction(self):
        """Create mock transaction."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_tag_repo):
        """Create TagHierarchyService instance."""
        return TagHierarchyService(mock_tag_repo)

    @pytest.mark.asyncio
    async def test_validate_tag_name_uniqueness_no_existing_tag(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test tag name uniqueness validation when no existing tag."""
        mock_tag_repo.find_by_name.return_value = None

        await service.validate_tag_name_uniqueness("work", mock_transaction)

        mock_tag_repo.find_by_name.assert_called_once_with("work")

    @pytest.mark.asyncio
    async def test_validate_tag_name_uniqueness_existing_tag_same_id(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test tag name uniqueness validation when existing tag has same ID."""
        existing_tag = Tag(name=TagName("work"), id=1)
        mock_tag_repo.find_by_name.return_value = existing_tag

        await service.validate_tag_name_uniqueness(
            "work", mock_transaction, exclude_tag_id=1
        )

        mock_tag_repo.find_by_name.assert_called_once_with("work")

    @pytest.mark.asyncio
    async def test_validate_tag_name_uniqueness_existing_tag_different_id_raises_error(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test tag name uniqueness validation raises error when existing tag has different ID."""
        existing_tag = Tag(name=TagName("work"), id=2)
        mock_tag_repo.find_by_name.return_value = existing_tag

        with pytest.raises(DuplicateTagNameError):
            await service.validate_tag_name_uniqueness(
                "work", mock_transaction, exclude_tag_id=1
            )

    @pytest.mark.asyncio
    async def test_validate_tag_name_uniqueness_existing_tag_no_exclude_raises_error(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test tag name uniqueness validation raises error when no exclude ID provided."""
        existing_tag = Tag(name=TagName("work"), id=2)
        mock_tag_repo.find_by_name.return_value = existing_tag

        with pytest.raises(DuplicateTagNameError):
            await service.validate_tag_name_uniqueness("work", mock_transaction)

    @pytest.mark.asyncio
    async def test_validate_parent_child_relationship_same_id_raises_error(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test parent-child relationship validation raises error when same ID."""
        with pytest.raises(ContactValidationError) as exc_info:
            await service.validate_parent_child_relationship(1, 1, mock_transaction)

        assert exc_info.value.field == "parent_id"
        assert "Tag cannot be its own parent" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_validate_parent_child_relationship_child_not_found_raises_error(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test parent-child relationship validation raises error when child not found."""
        mock_tag_repo.find_by_id.return_value = None

        with pytest.raises(TagNotFoundError):
            await service.validate_parent_child_relationship(1, 2, mock_transaction)

    @pytest.mark.asyncio
    async def test_validate_parent_child_relationship_valid(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test valid parent-child relationship."""
        child_tag = Tag(name=TagName("child"), id=2)
        parent_tag = Tag(name=TagName("parent"), id=1)

        # Mock the find_by_id calls for circular reference check
        def mock_find_by_id(tag_id):
            if tag_id == 2:
                return child_tag
            elif tag_id == 1:
                return parent_tag
            return None

        mock_tag_repo.find_by_id.side_effect = mock_find_by_id

        await service.validate_parent_child_relationship(1, 2, mock_transaction)

    @pytest.mark.asyncio
    async def test_check_circular_reference_direct_cycle_raises_error(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test circular reference check raises error for direct cycle."""
        # Create tags where 1 -> 2 -> 1 (circular)
        tag1 = Tag(name=TagName("tag1"), id=1, parent_id=2)
        tag2 = Tag(name=TagName("tag2"), id=2, parent_id=1)

        def mock_find_by_id(tag_id):
            if tag_id == 1:
                return tag1
            elif tag_id == 2:
                return tag2
            return None

        mock_tag_repo.find_by_id.side_effect = mock_find_by_id

        with pytest.raises(ContactValidationError) as exc_info:
            await service.validate_parent_child_relationship(1, 2, mock_transaction)

        assert exc_info.value.field == "parent_id"
        assert "child cannot be ancestor of parent" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_check_circular_reference_child_ancestor_raises_error(
        self, service, mock_tag_repo, mock_transaction
    ):
        """Test circular reference check raises error when child would become ancestor."""
        # Create hierarchy: 3 -> 2 -> 1, trying to make 1 parent of 3
        tag1 = Tag(name=TagName("tag1"), id=1, parent_id=None)
        tag2 = Tag(name=TagName("tag2"), id=2, parent_id=1)
        tag3 = Tag(name=TagName("tag3"), id=3, parent_id=2)

        def mock_find_by_id(tag_id):
            if tag_id == 1:
                return tag1
            elif tag_id == 2:
                return tag2
            elif tag_id == 3:
                return tag3
            return None

        mock_tag_repo.find_by_id.side_effect = mock_find_by_id

        with pytest.raises(ContactValidationError) as exc_info:
            await service.validate_parent_child_relationship(3, 1, mock_transaction)

        assert exc_info.value.field == "parent_id"
        assert "child cannot be ancestor of parent" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_get_tag_tree_with_root_id(self, service, mock_tag_repo):
        """Test getting tag tree with specific root ID."""
        children = [
            Tag(name=TagName("child1"), id=2, parent_id=1),
            Tag(name=TagName("child2"), id=3, parent_id=1),
        ]
        mock_tag_repo.get_children.return_value = children

        result = await service.get_tag_tree(root_tag_id=1)

        assert result == children
        mock_tag_repo.get_children.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_tag_tree_without_root_id(self, service, mock_tag_repo):
        """Test getting tag tree without root ID returns root tags."""
        root_tags = [Tag(name=TagName("root1"), id=1), Tag(name=TagName("root2"), id=2)]
        mock_tag_repo.get_root_tags.return_value = root_tags

        result = await service.get_tag_tree()

        assert result == root_tags
        mock_tag_repo.get_root_tags.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tag_path_single_tag(self, service, mock_tag_repo):
        """Test getting tag path for single tag."""
        tag = Tag(name=TagName("tag"), id=1, parent_id=None)
        mock_tag_repo.find_by_id.return_value = tag

        result = await service.get_tag_path(1)

        assert len(result) == 1
        assert result[0] == tag

    @pytest.mark.asyncio
    async def test_get_tag_path_hierarchy(self, service, mock_tag_repo):
        """Test getting tag path for tag hierarchy."""
        # Create hierarchy: grandparent -> parent -> child
        grandparent = Tag(name=TagName("grandparent"), id=1, parent_id=None)
        parent = Tag(name=TagName("parent"), id=2, parent_id=1)
        child = Tag(name=TagName("child"), id=3, parent_id=2)

        def mock_find_by_id(tag_id):
            if tag_id == 1:
                return grandparent
            elif tag_id == 2:
                return parent
            elif tag_id == 3:
                return child
            return None

        mock_tag_repo.find_by_id.side_effect = mock_find_by_id

        result = await service.get_tag_path(3)

        assert len(result) == 3
        assert result[0] == grandparent  # Root first
        assert result[1] == parent
        assert result[2] == child

    @pytest.mark.asyncio
    async def test_get_tag_path_tag_not_found(self, service, mock_tag_repo):
        """Test getting tag path when tag not found."""
        mock_tag_repo.find_by_id.return_value = None

        result = await service.get_tag_path(999)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_all_descendants_no_children(self, service, mock_tag_repo):
        """Test getting descendants when tag has no children."""
        mock_tag_repo.get_children.return_value = []

        result = await service.get_all_descendants(1)

        assert result == []
        mock_tag_repo.get_children.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_all_descendants_with_children(self, service, mock_tag_repo):
        """Test getting descendants when tag has children."""
        # Create hierarchy: 1 -> [2, 3], 2 -> [4]
        child1 = Tag(name=TagName("child1"), id=2, parent_id=1)
        child2 = Tag(name=TagName("child2"), id=3, parent_id=1)
        grandchild = Tag(name=TagName("grandchild"), id=4, parent_id=2)

        def mock_get_children(tag_id):
            if tag_id == 1:
                return [child1, child2]
            elif tag_id == 2:
                return [grandchild]
            elif tag_id == 3:
                return []
            return []

        mock_tag_repo.get_children.side_effect = mock_get_children

        result = await service.get_all_descendants(1)

        assert len(result) == 3
        assert child1 in result
        assert child2 in result
        assert grandchild in result
