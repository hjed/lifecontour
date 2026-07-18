"""Service layer for journal tag mutations.

Wraps journal tag create/delete and journal<->tag assignment in explicit units
of work so each write commits before the HTTP response is sent (issue #945),
keeping transaction ownership in the service layer rather than the controller.
"""

from dataclasses import replace
from uuid import UUID

from core_shared.models.journals import (
    JournalDomainError,
    JournalTagNotFoundError,
    JournalValidationError,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import JournalTagRepository
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.infrastructure.unit_of_work import transactional


class JournalTagInUseError(JournalDomainError):
    """Raised when attempting to delete a tag still assigned to journals (409)."""

    def __init__(self, message: str):
        super().__init__(message, 409)


class JournalTagService:
    """Service for persisting journal tags as committed units of work."""

    def __init__(
        self,
        tag_repo: JournalTagRepository,
        hierarchy_service: JournalTagHierarchyService,
    ) -> None:
        self.tag_repo = tag_repo
        self.hierarchy_service = hierarchy_service

    @transactional
    async def create_tag(
        self,
        tag: JournalTag,
        transaction: AsyncConnection,
    ) -> JournalTag:
        """Persist a new journal tag, mapping duplicate names to a domain error.

        Raises:
            JournalValidationError: If a tag with the same name already exists.
        """
        try:
            return await self.tag_repo.save(tag)
        except IntegrityError as e:
            # Check if it's a duplicate name error
            if "uq_journal_tags_name" in str(e) or "duplicate key" in str(e).lower():
                raise JournalValidationError(
                    "name",
                    f"A journal tag with the name '{tag.name}' already exists. "
                    "Tag names must be unique.",
                ) from e
            # Re-raise other integrity errors
            raise

    @transactional
    async def update_tag(
        self,
        tag_id: UUID,
        transaction: AsyncConnection,
        name: str | None = None,
        color: str | None = None,
        description: str | None = None,
        parent_id: UUID | None = None,
        set_parent_null: bool = False,
    ) -> JournalTag:
        """Update a journal tag, validating names, colour and hierarchy.

        Only the supplied fields change; omitting a field leaves it untouched.
        Clearing the parent requires the explicit ``set_parent_null`` flag,
        since a ``None`` ``parent_id`` is indistinguishable from "not supplied".

        Args:
            tag_id: The tag to update.
            transaction: Request connection; the write commits before the response.
            name: New name, if changing.
            color: New hex colour (``#RRGGBB``), if changing.
            description: New description, if changing.
            parent_id: New parent tag, if changing.
            set_parent_null: Move the tag to the root, clearing its parent.

        Raises:
            JournalTagNotFoundError: The tag, or a supplied parent, does not exist.
            JournalValidationError: The name is taken, the colour is malformed,
                or the parent would create a cycle.
        """
        existing = await self.tag_repo.find_by_id(tag_id)
        if existing is None:
            raise JournalTagNotFoundError(str(tag_id))

        changes: dict[str, object] = {}

        if name is not None and name != existing.name:
            await self.hierarchy_service.validate_tag_name_uniqueness(
                name, exclude_tag_id=tag_id
            )
            changes["name"] = name

        if color is not None and color != existing.color:
            changes["color"] = color

        if description is not None and description != existing.description:
            changes["description"] = description

        # An explicit parent wins over set_parent_null when both are supplied,
        # matching the contact TagService precedence.
        if parent_id is not None:
            if parent_id != existing.parent_id:
                await self.hierarchy_service.validate_parent(parent_id, tag_id)
                changes["parent_id"] = parent_id
        elif set_parent_null and existing.parent_id is not None:
            changes["parent_id"] = None

        if not changes:
            return existing

        # Rebuild through the dataclass so __post_init__ re-runs its name and
        # colour validation, then surface those as domain errors.
        try:
            updated = replace(existing, **changes)  # type: ignore[arg-type]
        except ValueError as e:
            field = "color" if "color" in str(e).lower() else "name"
            raise JournalValidationError(field, str(e)) from e

        try:
            return await self.tag_repo.save(updated)
        except IntegrityError as e:
            # A concurrent insert can take the name between the uniqueness
            # check above and this write; map it the same way create_tag does.
            if "uq_journal_tags_name" in str(e) or "duplicate key" in str(e).lower():
                raise JournalValidationError(
                    "name",
                    f"A journal tag with the name '{updated.name}' already exists. "
                    "Tag names must be unique.",
                ) from e
            raise

    @transactional
    async def delete_tag(
        self,
        tag_id: UUID,
        transaction: AsyncConnection,
    ) -> None:
        """Delete a journal tag after verifying it is not in use.

        Args:
            tag_id: The tag to delete (already validated to exist by the caller).
            transaction: Request connection; the write commits before the response.

        Raises:
            JournalTagInUseError: The tag is still assigned to one or more journals.
        """
        # Check if tag is in use by any journals. This prevents accidental
        # deletion of tags that are actively being used.
        check_query = text(
            """
            SELECT COUNT(*) as count
            FROM journal_tag_assignments
            WHERE tag_id = :tag_id
            """
        )
        result = await transaction.execute(check_query, {"tag_id": tag_id})
        row = result.fetchone()
        usage_count: int = row[0] if row else 0

        if usage_count > 0:
            tag = await self.tag_repo.find_by_id(tag_id)
            tag_name = tag.name if tag else str(tag_id)
            raise JournalTagInUseError(
                f"Cannot delete tag '{tag_name}' because it is assigned to "
                f"{usage_count} journal(s). "
                "Remove the tag from all journals before deleting it."
            )

        await self.tag_repo.delete(tag_id)

    @transactional
    async def assign_tag(
        self,
        journal_id: int,
        tag_id: UUID,
        transaction: AsyncConnection,
    ) -> None:
        """Assign an existing tag to a journal as a committed unit of work."""
        await self.tag_repo.assign_tag(journal_id, tag_id)

    @transactional
    async def remove_tag(
        self,
        journal_id: int,
        tag_id: UUID,
        transaction: AsyncConnection,
    ) -> None:
        """Remove a tag from a journal as a committed unit of work."""
        await self.tag_repo.remove_tag(journal_id, tag_id)
