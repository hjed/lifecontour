"""SQL implementation of ReviewItemRepository."""

import json
from typing import Any

from core_shared.models.journals.review_item import ReviewItem, ReviewReason
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import ReviewItemRepository


class SqlReviewItemRepository(ReviewItemRepository):
    """SQL implementation of ReviewItemRepository using SQLAlchemy Core.

    Uses ON CONFLICT DO NOTHING on the unique constraint to ensure
    idempotent creation of review items.
    """

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_review_item(self, row: Any) -> ReviewItem:
        """Convert a database row to a ReviewItem entity."""
        details = row.details
        if isinstance(details, str):
            details = json.loads(details)

        return ReviewItem(
            id=row.id,
            user_id=row.user_id,
            source_journal_id=row.source_journal_id,
            candidate_journal_id=row.candidate_journal_id,
            reason=ReviewReason(row.reason),
            confidence_score=row.confidence_score,
            details=details,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create(self, review_item: ReviewItem) -> ReviewItem:
        """Create a review item with idempotency.

        Uses ON CONFLICT DO NOTHING on the (source_journal_id, candidate_journal_id)
        unique constraint. If a duplicate exists, returns the existing item.
        """
        query = text(
            """
            INSERT INTO journal_review_items (
                user_id, source_journal_id, candidate_journal_id,
                reason, confidence_score, details, status
            )
            VALUES (
                :user_id, :source_journal_id, :candidate_journal_id,
                :reason, :confidence_score, :details, :status
            )
            ON CONFLICT ON CONSTRAINT uq_journal_review_items_source_candidate
            DO NOTHING
            RETURNING id, user_id, source_journal_id, candidate_journal_id,
                      reason, confidence_score, details, status,
                      created_at, updated_at
            """
        )

        details_json = (
            json.dumps(review_item.details) if review_item.details is not None else None
        )

        result = await self.conn.execute(
            query,
            {
                "user_id": review_item.user_id,
                "source_journal_id": review_item.source_journal_id,
                "candidate_journal_id": review_item.candidate_journal_id,
                "reason": review_item.reason.value,
                "confidence_score": review_item.confidence_score,
                "details": details_json,
                "status": review_item.status,
            },
        )
        row = result.fetchone()

        if row is None:
            # ON CONFLICT DO NOTHING — duplicate exists, fetch it
            existing = await self._find_by_source_and_candidate(
                review_item.source_journal_id,
                review_item.candidate_journal_id,
            )
            if existing:
                return existing
            # Should not reach here, but return original as fallback
            return review_item

        return self._row_to_review_item(row)

    async def find_pending_by_journal_id(self, journal_id: int) -> list[ReviewItem]:
        """Find all pending review items where a journal is the source."""
        query = text(
            """
            SELECT id, user_id, source_journal_id, candidate_journal_id,
                   reason, confidence_score, details, status,
                   created_at, updated_at
            FROM journal_review_items
            WHERE source_journal_id = :journal_id
            AND status = 'pending'
            ORDER BY confidence_score DESC
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()
        return [self._row_to_review_item(row) for row in rows]

    async def _find_by_source_and_candidate(
        self, source_journal_id: int, candidate_journal_id: int
    ) -> ReviewItem | None:
        """Find a review item by source and candidate journal IDs."""
        query = text(
            """
            SELECT id, user_id, source_journal_id, candidate_journal_id,
                   reason, confidence_score, details, status,
                   created_at, updated_at
            FROM journal_review_items
            WHERE source_journal_id = :source_journal_id
            AND candidate_journal_id = :candidate_journal_id
            """
        )
        result = await self.conn.execute(
            query,
            {
                "source_journal_id": source_journal_id,
                "candidate_journal_id": candidate_journal_id,
            },
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_review_item(row)
