"""Match candidate detector for journal duplicate/similarity detection.

Centralized service that evaluates whether an incoming journal matches
existing journals, using an AI-based similarity assessor for comparison.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from core_shared.models.journals.review_item import ReviewReason

from app.core.journal.services.title_similarity_assessor import TitleSimilarityAssessor

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
    """A detected match candidate with scoring details.

    Attributes:
        journal_id: ID of the existing journal that matches
        reason: Why this was flagged (duplicate, needs review, etc.)
        confidence_score: 0.0-1.0 overall confidence
        details: Additional details about the match
    """

    journal_id: int
    reason: ReviewReason
    confidence_score: float
    details: dict[str, Any]


class MatchCandidateDetector:
    """Detects match candidates for incoming journals.

    Uses a two-step process:
    1. Date gate: Only consider journals on the same day (fast filter)
    2. AI assessment: Use TitleSimilarityAssessor for detailed comparison

    The detector is stateless and injected via DI.
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
        """Detect match candidates from existing journals.

        Centralized scoring rules:
        1. Same start date required (date gate)
        2. AI similarity assessment via TitleSimilarityAssessor
        3. Candidates above threshold classified by confidence level

        Args:
            incoming_title: Title of the incoming journal
            incoming_content: Content of the incoming journal
            incoming_start: Start datetime of the incoming journal
            incoming_end: End datetime of the incoming journal
            existing_journals: List of existing journals to compare against

        Returns:
            List of match candidates sorted by confidence (descending)
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
            except Exception:
                logger.exception(
                    "Failed to assess similarity for candidate",
                    candidate_journal_id=journal.id,
                )
                raise

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)

        return candidates
