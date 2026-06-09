"""Service layer for journal tag mutations.

Wraps journal tag create/delete and journal<->tag assignment in explicit units
of work so each write commits before the HTTP response is sent (issue #945),
keeping transaction ownership in the service layer rather than the controller.
"""

from uuid import UUID

from core_shared.models.journals import JournalDomainError, JournalValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import JournalTagRepository
from app.infrastructure.unit_of_work import transactional


class JournalTagInUseError(JournalDomainError):
    """Raised when attempting to delete a tag still assigned to journals (409)."""

    def __init__(self, message: str):
        super().__init__(message, 409)


class JournalTagService:
    """Service for persisting journal tags as committed units of work."""

    def __init__(self, tag_repo: JournalTagRepository) -> None:
        self.tag_repo = tag_repo

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
