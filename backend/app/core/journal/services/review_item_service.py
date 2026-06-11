"""Service layer for journal review item mutations.

Wraps review-item creation and the auto-merge batch in explicit units of work so
each write commits before the HTTP response is sent (issue #945), keeping
transaction ownership in the service layer rather than the controller.
"""

import structlog
from core_shared.models.journals.review_item import ReviewItem
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import ReviewItemRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.unit_of_work import savepoint, transactional

logger = structlog.get_logger()


class ReviewItemService:
    """Service for persisting review items as committed units of work."""

    def __init__(
        self,
        review_item_repo: ReviewItemRepository,
        journal_service: JournalService,
        journal_merge_service: JournalMergeService,
    ) -> None:
        self.review_item_repo = review_item_repo
        self.journal_service = journal_service
        self.journal_merge_service = journal_merge_service

    @transactional
    async def dismiss(
        self,
        item_id: int,
        user_id: str,
        transaction: AsyncConnection,
    ) -> ReviewItem | None:
        """Dismiss a review item as a committed unit of work.

        Returns the updated review item, or ``None`` if no item with the given
        id exists.
        """
        return await self.review_item_repo.update_status(
            review_item_id=item_id,
            new_status="dismissed",
            user_id=user_id,
        )

    @transactional
    async def create_review_item(
        self,
        review_item: ReviewItem,
        transaction: AsyncConnection,
    ) -> tuple[ReviewItem, bool]:
        """Create a review item as a committed unit of work.

        Returns the created item and a flag indicating whether it was newly
        created (vs already existed for the journal pair).
        """
        return await self.review_item_repo.create(review_item)

    @transactional
    async def auto_merge_review_items(
        self,
        user_id: str,
        transaction: AsyncConnection,
    ) -> tuple[int, int, int, list[str]]:
        """Auto-merge all pending review items with no base-field conflicts.

        For each pending review item where the source and candidate journals have
        no conflicting base fields, merge the source into the candidate. Each
        merge runs inside its own SAVEPOINT so a single failure rolls back only
        that merge and the loop continues.

        Returns:
            A tuple of (merged_count, skipped_count, remaining_count, errors).
        """
        pending_items = await self.review_item_repo.find_pending_by_user(
            user_id, limit=100, offset=0
        )

        merged_count = 0
        skipped_count = 0
        errors: list[str] = []

        for item in pending_items:
            source_journal = await self.journal_service.get_journal(
                item.source_journal_id
            )
            candidate_journal = await self.journal_service.get_journal(
                item.candidate_journal_id
            )

            if not source_journal or not candidate_journal:
                # One of the journals was deleted; dismiss the review item
                if item.id is not None:
                    await self.review_item_repo.update_status(
                        item.id, new_status="resolved", user_id=user_id
                    )
                skipped_count += 1
                continue

            # Ensure we are not merging cross-tenant
            if (
                source_journal.user_id != user_id
                or candidate_journal.user_id != user_id
            ):
                skipped_count += 1
                continue

            # Check for base-field conflicts
            if self.journal_merge_service.has_base_conflicts(
                candidate_journal, source_journal
            ):
                skipped_count += 1
                continue

            # No conflicts - auto-merge (source → candidate as target)
            try:
                async with savepoint(transaction):
                    await self.journal_merge_service.merge_journals(
                        target_id=item.candidate_journal_id,
                        source_id=item.source_journal_id,
                        transaction=transaction,
                    )
                merged_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Auto-merge failed for review item",
                    review_item_id=item.id,
                    error=str(exc),
                )
                errors.append(
                    f"Failed to merge journals {item.source_journal_id} → "
                    f"{item.candidate_journal_id}: Internal error occurred."
                )

        remaining_count = await self.review_item_repo.count_pending_by_user(user_id)

        return merged_count, skipped_count, remaining_count, errors
