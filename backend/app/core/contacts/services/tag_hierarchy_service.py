"""Tag hierarchy and validation service."""

from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.exceptions import ContactValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import (
    DuplicateTagNameError,
    TagNotFoundError,
)
from app.core.contacts.models.repositories import TagRepository


class TagHierarchyService:
    """Service for managing tag hierarchies and validation."""

    def __init__(self, tag_repo: TagRepository):
        self.tag_repo = tag_repo

    async def validate_tag_name_uniqueness(
        self,
        name: str,
        _transaction: AsyncConnection,
        exclude_tag_id: int | None = None,
    ) -> None:
        """Validate that tag name is unique."""
        existing_tag = await self.tag_repo.find_by_name(name)

        if existing_tag:
            if exclude_tag_id is None or existing_tag.id != exclude_tag_id:
                raise DuplicateTagNameError(name)

    async def validate_parent_child_relationship(
        self, parent_id: int, child_id: int, transaction: AsyncConnection
    ) -> None:
        """Validate parent-child tag relationship."""
        if parent_id == child_id:
            raise ContactValidationError("parent_id", "Tag cannot be its own parent")

        # Check if parent exists
        parent_tag = await self.tag_repo.find_by_id(
            child_id
        )  # Note: checking child_id for parent
        if not parent_tag:
            raise TagNotFoundError(child_id)

        # Check for circular references (simplified - could be more comprehensive)
        await self._check_circular_reference(parent_id, child_id, transaction)

    async def _check_circular_reference(
        self, parent_id: int, child_id: int, _transaction: AsyncConnection
    ) -> None:
        """Check for circular references in tag hierarchy."""
        # Get all ancestors of the proposed parent
        current_id: int | None = parent_id
        visited = set()

        while current_id is not None:
            if current_id in visited:
                # Found a cycle
                raise ContactValidationError(
                    "parent_id", "Circular reference detected in tag hierarchy"
                )

            if current_id == child_id:
                # The child would become an ancestor of itself
                raise ContactValidationError(
                    "parent_id",
                    "Cannot create circular reference: child cannot be ancestor of parent",
                )

            visited.add(current_id)

            # Get parent of current tag
            current_tag = await self.tag_repo.find_by_id(current_id)
            if current_tag:
                current_id = current_tag.parent_id
            else:
                break

    async def get_tag_tree(
        self,
        root_tag_id: int | None = None,
        _transaction: AsyncConnection | None = None,
    ) -> list[Tag]:
        """Get tag tree starting from root or specific tag."""
        if root_tag_id:
            return await self.tag_repo.get_children(root_tag_id)
        else:
            return await self.tag_repo.get_root_tags()

    async def get_tag_path(
        self, tag_id: int, _transaction: AsyncConnection | None = None
    ) -> list[Tag]:
        """Get the full path from root to the specified tag."""
        path: list[Tag] = []
        current_id: int | None = tag_id

        while current_id is not None:
            tag = await self.tag_repo.find_by_id(current_id)
            if not tag:
                break

            path.insert(0, tag)  # Insert at beginning to build path from root
            current_id = tag.parent_id

        return path

    async def get_all_descendants(
        self, tag_id: int, _transaction: AsyncConnection | None = None
    ) -> list[Tag]:
        """Get all descendant tags of the specified tag."""
        descendants: list[Tag] = []

        # Get direct children
        children = await self.tag_repo.get_children(tag_id)

        for child in children:
            descendants.append(child)
            # Recursively get descendants of each child
            if child.id:
                child_descendants = await self.get_all_descendants(
                    child.id, _transaction
                )
                descendants.extend(child_descendants)

        return descendants

    async def get_all_descendants_bulk(
        self, tag_ids: list[int], _transaction: AsyncConnection | None = None
    ) -> list[Tag]:
        """Get all descendant tags for multiple tags in a single query."""
        if not tag_ids:
            return []
        return await self.tag_repo.get_descendants_for_tags(tag_ids)
