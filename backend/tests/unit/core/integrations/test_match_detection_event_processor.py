"""
Unit tests for MatchDetectionEventProcessor.

Tests that the processor correctly handles journal_review.detect_matches events
for Strava-sourced journals, including same-day matching, ReviewItem creation,
and edge cases.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.journals.review_item import ReviewReason
from core_shared.models.outbox import OutboxEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.match_detection_event_processor import (
    MatchDetectionEventProcessor,
)
from app.core.journal.services.match_candidate_detector import (
    MatchCandidate,
    MatchCandidateDetector,
)


def _make_match_detection_event(
    *,
    journal_id: int = 42,
    user_id: str = "1",
    journal_title: str = "Morning Run",
    journal_content: str = "Easy jog around the park",
    event_date_range_start: str = "2026-03-20T08:00:00+00:00",
    event_date_range_end: str = "2026-03-20T09:00:00+00:00",
) -> OutboxEvent:
    """Build a sample journal_review.detect_matches outbox event."""
    return OutboxEvent(
        id=uuid4(),
        event_type="journal_review.detect_matches",
        event_data={
            "journal_id": journal_id,
            "user_id": user_id,
            "journal_title": journal_title,
            "journal_content": journal_content,
            "event_date_range_start": event_date_range_start,
            "event_date_range_end": event_date_range_end,
            "created_at": datetime.now(UTC).isoformat(),
        },
        created_at=datetime.now(UTC),
        retry_count=0,
    )


def _make_db_row(
    *,
    journal_id: int,
    title: str,
    content: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
) -> MagicMock:
    """Create a mock DB row for same-day journal query."""
    row = MagicMock()
    row.id = journal_id
    row.title = title
    row.content = content
    row.event_date_range_start = start or datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
    row.event_date_range_end = end or datetime(2026, 3, 20, 11, 0, tzinfo=UTC)
    return row


class TestMatchDetectionEventProcessor:
    """Tests for the MatchDetectionEventProcessor."""

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        return AsyncMock(spec=AsyncConnection)

    @pytest.fixture
    def mock_detector(self) -> AsyncMock:
        return AsyncMock(spec=MatchCandidateDetector)

    @pytest.fixture
    def mock_review_repo(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def processor(
        self,
        mock_connection: AsyncMock,
        mock_detector: AsyncMock,
        mock_review_repo: AsyncMock,
    ) -> MatchDetectionEventProcessor:
        return MatchDetectionEventProcessor(
            connection=mock_connection,
            match_candidate_detector=mock_detector,
            review_item_repository=mock_review_repo,
        )

    @pytest.mark.asyncio
    async def test_strava_match_detection_creates_review_items(
        self,
        processor: MatchDetectionEventProcessor,
        mock_connection: AsyncMock,
        mock_detector: AsyncMock,
        mock_review_repo: AsyncMock,
    ) -> None:
        """Match detection for Strava journal should create ReviewItem entries."""
        event = _make_match_detection_event(
            journal_id=42,
            journal_title="Morning Run",
            journal_content="Easy jog",
        )

        # Mock same-day query to return an existing journal
        same_day_result = MagicMock()
        same_day_result.fetchall.return_value = [
            _make_db_row(journal_id=10, title="Saturday Bushwalk"),
        ]
        mock_connection.execute.return_value = same_day_result

        # Mock detector to find a match
        mock_detector.detect_candidates.return_value = [
            MatchCandidate(
                journal_id=10,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=0.85,
                details={"ai_similarity_score": 0.85},
            ),
        ]

        # Mock repo to insert successfully
        mock_review_repo.create.return_value = (MagicMock(), True)

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["candidates_found"] == 1
        assert result["review_items_created"] == 1

    @pytest.mark.asyncio
    async def test_no_same_day_journals_returns_zero_candidates(
        self,
        processor: MatchDetectionEventProcessor,
        mock_connection: AsyncMock,
        mock_detector: AsyncMock,
    ) -> None:
        """No same-day journals means no candidates."""
        event = _make_match_detection_event()

        # Mock empty result from same-day query
        same_day_result = MagicMock()
        same_day_result.fetchall.return_value = []
        mock_connection.execute.return_value = same_day_result

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["candidates_found"] == 0

    @pytest.mark.asyncio
    async def test_cross_integration_strava_and_google_both_detected(
        self,
        processor: MatchDetectionEventProcessor,
        mock_connection: AsyncMock,
        mock_detector: AsyncMock,
        mock_review_repo: AsyncMock,
    ) -> None:
        """Strava activity should match against Google Calendar journal on same day."""
        event = _make_match_detection_event(
            journal_id=42,
            journal_title="Saturday Bushwalk",
        )

        # Two existing journals on same day (one from Google, one manual)
        same_day_result = MagicMock()
        same_day_result.fetchall.return_value = [
            _make_db_row(journal_id=10, title="Saturday Bushwalk"),
            _make_db_row(journal_id=11, title="Dentist Appointment"),
        ]
        mock_connection.execute.return_value = same_day_result

        # Detector finds one match
        mock_detector.detect_candidates.return_value = [
            MatchCandidate(
                journal_id=10,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=0.90,
                details={"ai_similarity_score": 0.90},
            ),
        ]

        mock_review_repo.create.return_value = (MagicMock(), True)

        result = await processor.process_event(event)

        assert result["candidates_found"] == 1
        assert result["review_items_created"] == 1

        # Verify detector was called with both existing journals
        call_args = mock_detector.detect_candidates.call_args
        assert len(call_args.kwargs["existing_journals"]) == 2

    @pytest.mark.asyncio
    async def test_duplicate_review_item_not_counted(
        self,
        processor: MatchDetectionEventProcessor,
        mock_connection: AsyncMock,
        mock_detector: AsyncMock,
        mock_review_repo: AsyncMock,
    ) -> None:
        """If ReviewItem already exists (duplicate), it should not be counted as created."""
        event = _make_match_detection_event()

        same_day_result = MagicMock()
        same_day_result.fetchall.return_value = [
            _make_db_row(journal_id=10, title="Morning Run"),
        ]
        mock_connection.execute.return_value = same_day_result

        mock_detector.detect_candidates.return_value = [
            MatchCandidate(
                journal_id=10,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=0.85,
                details={},
            ),
        ]

        # Simulate duplicate — inserted=False
        mock_review_repo.create.return_value = (MagicMock(), False)

        result = await processor.process_event(event)

        assert result["candidates_found"] == 1
        assert result["review_items_created"] == 0

    @pytest.mark.asyncio
    async def test_skips_when_dependencies_not_available(
        self,
        mock_connection: AsyncMock,
    ) -> None:
        """Processor should skip when dependencies are not wired (None)."""
        processor = MatchDetectionEventProcessor(
            connection=mock_connection,
            match_candidate_detector=None,
            review_item_repository=None,
        )

        event = _make_match_detection_event()
        result = await processor.process_event(event)

        assert result["status"] == "skipped"
        assert result["reason"] == "dependencies_not_available"

    @pytest.mark.asyncio
    async def test_multi_strava_activity_detection(
        self,
        processor: MatchDetectionEventProcessor,
        mock_connection: AsyncMock,
        mock_detector: AsyncMock,
        mock_review_repo: AsyncMock,
    ) -> None:
        """Two Strava activities on same day should both be flagged."""
        # Second Strava activity triggers match detection
        event = _make_match_detection_event(
            journal_id=43,
            journal_title="Blue Mountains Hike - Part 2",
            event_date_range_start="2026-03-20T12:00:00+00:00",
            event_date_range_end="2026-03-20T16:00:00+00:00",
        )

        same_day_result = MagicMock()
        same_day_result.fetchall.return_value = [
            _make_db_row(
                journal_id=42,
                title="Blue Mountains Hike - Part 1",
                start=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
                end=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
            ),
        ]
        mock_connection.execute.return_value = same_day_result

        mock_detector.detect_candidates.return_value = [
            MatchCandidate(
                journal_id=42,
                reason=ReviewReason.DUPLICATE_JOURNAL,
                confidence_score=0.92,
                details={"ai_similarity_score": 0.92},
            ),
        ]

        mock_review_repo.create.return_value = (MagicMock(), True)

        result = await processor.process_event(event)

        assert result["status"] == "success"
        assert result["candidates_found"] == 1
        assert result["review_items_created"] == 1
