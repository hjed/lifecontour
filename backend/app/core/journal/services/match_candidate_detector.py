"""Match candidate detector for journal duplicate/similarity detection.

Centralized service that evaluates whether an incoming journal matches
existing journals, using an AI-based similarity assessor for comparison.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from core_shared.models.journals.review_item import ReviewReason

from app.core.journal.services.title_similarity_assessor import (
    SimilarityAssessmentError,
    TitleSimilarityAssessor,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class CandidateJournalData:
    """Lightweight view of an existing journal for matching purposes.

    Contains only the fields needed for match candidate detection,
    avoiding loading full journal entities.

    Attributes:
        id: Journal ID
        title: Journal title
        content: Journal content/description
        event_date_range_start: Start of event date range
        event_date_range_end: End of event date range
    """

    id: int
    title: str
    content: str
    event_date_range_start: datetime
    event_date_range_end: datetime


@dataclass(frozen=True)
class MatchCandidate:
    """A journal that may be a match for an incoming event."""

    journal_id: int
    reason: ReviewReason
    confidence_score: float
    details: dict[str, Any]


class MatchCandidateDetector:
    """Detects potential match candidates for a new journal entry.

    Uses an AI-based similarity assessor to compare incoming events
    against existing journals on the same day.
    """

    CONFIDENCE_THRESHOLD = 0.6
    HIGH_CONFIDENCE_THRESHOLD = 0.8

    def __init__(self, similarity_assessor: TitleSimilarityAssessor) -> None:
        """Initialize with a similarity assessor.

        Args:
            similarity_assessor: AI-based assessor for comparing events
        """
        self._assessor = similarity_assessor

    async def detect_candidates(
        self,
        incoming_title: str,
        incoming_content: str,
        incoming_start: datetime,
        incoming_end: datetime,
        existing_journals: list[CandidateJournalData],
    ) -> list[MatchCandidate]:
        """Detect potential match candidates for an incoming event.

        Args:
            incoming_title: Title of the incoming event
            incoming_content: Content/description of the incoming event
            incoming_start: Start datetime of the incoming event
            incoming_end: End datetime of the incoming event
            existing_journals: List of existing journals to compare against

        Returns:
            List of match candidates sorted by confidence (descending)

        Raises:
            Exception: Transport/API errors from the similarity assessor
                propagate so the outbox retry mechanism can handle them.
        """
        if not existing_journals:
            return []

        # Step 1: Date gate — only same-day journals
        same_day = [
            j
            for j in existing_journals
            if j.event_date_range_start.date() == incoming_start.date()
        ]

        if not same_day:
            return []

        # Step 2: AI assessment for each same-day journal
        # SimilarityAssessmentError (parse/response-shape failures) are caught
        # and the candidate is skipped. Transport/API errors propagate so the
        # outbox retry mechanism can handle transient outages.
        candidates: list[MatchCandidate] = []
        for journal in same_day:
            try:
                ai_score = await self._assessor.assess_similarity(
                    title_a=incoming_title,
                    content_a=incoming_content,
                    start_a=incoming_start,
                    end_a=incoming_end,
                    title_b=journal.title,
                    content_b=journal.content,
                    start_b=journal.event_date_range_start,
                    end_b=journal.event_date_range_end,
                )

                if ai_score >= self.CONFIDENCE_THRESHOLD:
                    reason = (
                        ReviewReason.DUPLICATE_JOURNAL
                        if ai_score >= self.HIGH_CONFIDENCE_THRESHOLD
                        else ReviewReason.NEEDS_REVIEW
                    )

                    candidates.append(
                        MatchCandidate(
                            journal_id=journal.id,
                            reason=reason,
                            confidence_score=ai_score,
                            details={
                                "ai_similarity_score": ai_score,
                                "candidate_title": journal.title,
                                "incoming_title": incoming_title,
                            },
                        )
                    )
            except SimilarityAssessmentError:
                logger.warning(
                    "Unparseable similarity response, skipping candidate",
                    candidate_journal_id=journal.id,
                )
                continue

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)

        return candidates
