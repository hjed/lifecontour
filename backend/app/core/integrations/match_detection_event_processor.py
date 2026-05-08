"""
Processor for match detection outbox events.

Handles the journal_review.detect_matches event by querying
same-day journals, running AI similarity assessment, and creating ReviewItems
for matches.
"""

from typing import Any

import structlog
from core_shared.models.journals import ReviewItem
from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import MatchDetectionEventData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    EVENT_TYPE_JOURNAL_REVIEW_DETECT_MATCHES,
)
from app.core.journal.adapters.sql.review_item_repository import (
    SqlReviewItemRepository,
)
from app.core.journal.services.match_candidate_detector import (
    CandidateJournalData,
    MatchCandidateDetector,
)

logger = structlog.get_logger()


class MatchDetectionEventProcessor:
    """Processor for journal_review.detect_matches outbox events."""

    def __init__(
        self,
        connection: AsyncConnection,
        match_candidate_detector: MatchCandidateDetector | None,
        review_item_repository: SqlReviewItemRepository | None,
    ):
        """
        Initialize the match detection event processor.

        Args:
            connection: Async database connection
            match_candidate_detector: Service for AI-assisted match detection
            review_item_repository: Repository for persisting match suggestions
        """
        self.connection = connection
        self.match_candidate_detector = match_candidate_detector
        self.review_item_repository = review_item_repository

    async def process_event(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_review.detect_matches event.

        Queries same-day journals, runs AI similarity assessment via
        MatchCandidateDetector, and creates ReviewItems for matches.
        """
        from datetime import datetime as dt

        if self.match_candidate_detector is None or self.review_item_repository is None:
            logger.warning(
                "Match detection dependencies not available, skipping",
                event_id=event.event_id,
            )
            return {
                "status": "skipped",
                "event_type": EVENT_TYPE_JOURNAL_REVIEW_DETECT_MATCHES,
                "reason": "dependencies_not_available",
            }

        event_data: dict[str, Any] = event.event_data  # type: ignore
        payload = MatchDetectionEventData.model_validate(event_data)
        journal_id = payload.journal_id
        user_id = payload.user_id
        journal_title = payload.journal_title
        journal_content = payload.journal_content
        start_str = payload.event_date_range_start
        end_str = payload.event_date_range_end

        incoming_start = dt.fromisoformat(start_str.replace("Z", "+00:00"))
        incoming_end = dt.fromisoformat(end_str.replace("Z", "+00:00"))

        # Use a range predicate instead of DATE() wrapping so the query remains index-friendly.
        day_start = dt(
            incoming_start.year,
            incoming_start.month,
            incoming_start.day,
            tzinfo=incoming_start.tzinfo,
        )
        from datetime import timedelta

        day_end = day_start + timedelta(days=1)

        # Query same-day journals for the user (excluding the source journal)
        same_day_rows = await self.connection.execute(
            text("""
                SELECT j.id, j.title, j.content,
                       j.event_date_range_start, j.event_date_range_end
                FROM journals j
                WHERE j.user_id = :user_id
                  AND j.id != :journal_id
                  AND j.event_date_range_start >= :day_start
                  AND j.event_date_range_start < :day_end
            """),
            {
                "user_id": user_id,
                "journal_id": journal_id,
                "day_start": day_start,
                "day_end": day_end,
            },
        )
        rows = same_day_rows.fetchall()

        if not rows:
            logger.info(
                "No same-day journals found for match detection",
                journal_id=journal_id,
            )
            return {
                "status": "success",
                "event_type": EVENT_TYPE_JOURNAL_REVIEW_DETECT_MATCHES,
                "journal_id": journal_id,
                "candidates_found": 0,
            }

        existing_journals = [
            CandidateJournalData(
                id=row.id,
                title=row.title,
                content=row.content or "",
                event_date_range_start=row.event_date_range_start,
                event_date_range_end=row.event_date_range_end,
            )
            for row in rows
        ]

        # Run AI-assisted match detection
        candidates = await self.match_candidate_detector.detect_candidates(
            incoming_title=journal_title,
            incoming_content=journal_content,
            incoming_start=incoming_start,
            incoming_end=incoming_end,
            existing_journals=existing_journals,
        )

        # Create review items for each match candidate
        review_items_created = 0
        for candidate in candidates:
            review_item = ReviewItem(
                user_id=user_id,
                source_journal_id=journal_id,
                candidate_journal_id=candidate.journal_id,
                reason=candidate.reason,
                confidence_score=candidate.confidence_score,
                details=candidate.details,
            )
            _, inserted = await self.review_item_repository.create(review_item)
            if inserted:
                review_items_created += 1

        logger.info(
            "Match detection completed",
            journal_id=journal_id,
            candidates_found=len(candidates),
            review_items_created=review_items_created,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_REVIEW_DETECT_MATCHES,
            "journal_id": journal_id,
            "candidates_found": len(candidates),
            "review_items_created": review_items_created,
        }
