"""Journal tag hierarchy and name validation.

Mirrors the contact ``TagHierarchyService`` validation rules for journal tags,
which are keyed by UUID rather than integer id. Kept separate from
``JournalTagService`` so the rules can be exercised without a unit of work.
"""

from uuid import UUID

from core_shared.models.journals import (
    JournalTagNotFoundError,
    JournalValidationError,
)

from app.core.journal.models.repositories import JournalTagRepository


class JournalTagHierarchyService:
    """Validates journal tag names and parent-child relationships."""

    def __init__(self, tag_repo: JournalTagRepository) -> None:
        self.tag_repo = tag_repo

    async def validate_tag_name_uniqueness(
        self,
        name: str,
        exclude_tag_id: UUID | None = None,
    ) -> None:
        """Ensure no other tag already holds ``name``.

        The repository lookup is case-insensitive (``LOWER(name)``), matching
        the unique index, so re-casing a tag's own name is not a conflict.

        Raises:
            JournalValidationError: Another tag already uses this name.
        """
        existing_tag = await self.tag_repo.find_by_name(name)

        if existing_tag and existing_tag.id != exclude_tag_id:
            raise JournalValidationError(
                "name",
                f"A journal tag with the name '{name}' already exists. "
                "Tag names must be unique.",
            )

    async def validate_parent(self, parent_id: UUID, child_id: UUID) -> None:
        """Ensure ``parent_id`` is a legal parent for ``child_id``.

        Raises:
            JournalValidationError: The parent is the tag itself, or assigning
                it would make the tag its own ancestor.
            JournalTagNotFoundError: The proposed parent does not exist.
        """
        if parent_id == child_id:
            raise JournalValidationError("parent_id", "A tag cannot be its own parent")

        if await self.tag_repo.find_by_id(parent_id) is None:
            raise JournalTagNotFoundError(str(parent_id))

        await self._check_circular_reference(parent_id, child_id)

    async def _check_circular_reference(self, parent_id: UUID, child_id: UUID) -> None:
        """Walk the proposed parent's ancestry looking for ``child_id``."""
        current_id: UUID | None = parent_id
        visited: set[UUID] = set()

        while current_id is not None:
            if current_id in visited:
                raise JournalValidationError(
                    "parent_id", "Circular reference detected in tag hierarchy"
                )

            if current_id == child_id:
                raise JournalValidationError(
                    "parent_id",
                    "Cannot create circular reference: a tag cannot become its "
                    "own ancestor",
                )

            visited.add(current_id)

            current_tag = await self.tag_repo.find_by_id(current_id)
            if current_tag is None:
                break
            current_id = current_tag.parent_id
