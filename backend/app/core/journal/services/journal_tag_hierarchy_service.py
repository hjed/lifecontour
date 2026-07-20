"""Journal tag hierarchy and name validation.

Mirrors the contact ``TagHierarchyService`` validation rules for journal tags,
which are keyed by UUID rather than integer id. Kept separate from
``JournalTagService`` so the rules can be exercised without a unit of work.
"""

from enum import Enum
from uuid import UUID

from core_shared.models.journals import (
    JournalTagNotFoundError,
    JournalValidationError,
)

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import JournalTagRepository


class _AncestryWalk(Enum):
    """The outcome of walking a tag's ancestry chain."""

    FOUND = "found"
    """The tag being looked for is an ancestor of the starting tag."""

    CYCLE = "cycle"
    """The chain loops back on itself before terminating (corrupt data)."""

    CLEAR = "clear"
    """The chain reached a root without finding the tag."""


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

    async def validate_merge_target(self, source_id: UUID, target_id: UUID) -> None:
        """Ensure ``source_id`` may legally be merged into ``target_id``.

        Merging into a descendant of the source is rejected: the descendant's
        ancestry runs through the tag that is about to be deleted, so the
        surviving hierarchy would be nonsense.

        Raises:
            JournalValidationError: The target is the source itself or one of
                its descendants.
            JournalTagNotFoundError: Either tag does not exist.
        """
        if source_id == target_id:
            raise JournalValidationError(
                "target_tag_id", "A tag cannot be merged into itself"
            )

        if await self.tag_repo.find_by_id(source_id) is None:
            raise JournalTagNotFoundError(str(source_id))
        if await self.tag_repo.find_by_id(target_id) is None:
            raise JournalTagNotFoundError(str(target_id))

        # The target is a descendant of the source exactly when the source
        # appears in the target's ancestry — the same walk re-parenting makes.
        outcome = await self._walk_ancestry(target_id, source_id)

        if outcome == _AncestryWalk.FOUND:
            raise JournalValidationError(
                "target_tag_id", "Cannot merge a tag into its own descendant"
            )
        if outcome == _AncestryWalk.CYCLE:
            raise JournalValidationError(
                "target_tag_id",
                "Circular reference detected in tag hierarchy",
            )

    async def get_all_descendants_bulk(self, tag_ids: list[UUID]) -> list[JournalTag]:
        """Get all descendant tags for multiple tags in a single query.

        Mirrors the contact ``TagHierarchyService.get_all_descendants_bulk`` so
        journal list filtering can expand a parent tag to its whole subtree.
        """
        if not tag_ids:
            return []
        return await self.tag_repo.get_descendants_for_tags(tag_ids)

    async def _check_circular_reference(self, parent_id: UUID, child_id: UUID) -> None:
        """Walk the proposed parent's ancestry looking for ``child_id``."""
        outcome = await self._walk_ancestry(parent_id, child_id)

        if outcome == _AncestryWalk.FOUND:
            raise JournalValidationError(
                "parent_id",
                "Cannot create circular reference: a tag cannot become its "
                "own ancestor",
            )
        if outcome == _AncestryWalk.CYCLE:
            raise JournalValidationError(
                "parent_id", "Circular reference detected in tag hierarchy"
            )

    async def _walk_ancestry(self, start_id: UUID, looking_for: UUID) -> _AncestryWalk:
        """Walk ``start_id``'s ancestry looking for ``looking_for``.

        Returns which of the three outcomes the walk reached, leaving the
        caller to phrase the error for its own operation — re-parenting and
        merging reject the same shapes but blame different fields, and a
        pre-existing cycle in the data is a distinct condition from the tag
        actually being found.
        """
        current_id: UUID | None = start_id
        visited: set[UUID] = set()

        while current_id is not None:
            if current_id in visited:
                return _AncestryWalk.CYCLE

            if current_id == looking_for:
                return _AncestryWalk.FOUND

            visited.add(current_id)

            current_tag = await self.tag_repo.find_by_id(current_id)
            if current_tag is None:
                break
            current_id = current_tag.parent_id

        return _AncestryWalk.CLEAR
