"""Unit tests for MatchCandidateDetector service."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals.review_item import ReviewReason

from app.core.journal.services.match_candidate_detector import (
    CandidateJournalData,
    MatchCandidateDetector,
)
from app.core.journal.services.title_similarity_assessor import (
    SimilarityAssessmentError,
    TitleSimilarityAssessor,
)


@pytest.mark.unit
class TestMatchCandidateDetector:
    """Test match candidate detection logic."""

    @pytest.fixture
    def mock_assessor(self) -> AsyncMock:
        """Create a mock TitleSimilarityAssessor."""
        return AsyncMock(spec=TitleSimilarityAssessor)

    @pytest.fixture
    def detector(self, mock_assessor: AsyncMock) -> MatchCandidateDetector:
        """Create a detector with mock assessor."""
        return MatchCandidateDetector(similarity_assessor=mock_assessor)

    @pytest.fixture
    def base_start(self) -> datetime:
        """Common start datetime for tests."""
        return datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)

    @pytest.fixture
    def base_end(self) -> datetime:
        """Common end datetime for tests."""
        return datetime(2024, 3, 15, 11, 0, 0, tzinfo=UTC)

    async def test_empty_existing_journals_returns_empty(
        self,
        detector: MatchCandidateDetector,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that no existing journals produces no candidates."""
        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="Agenda for today",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[],
        )

        assert result == []

    async def test_different_day_journals_excluded(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that journals on a different day are excluded (date gate)."""
        different_day = CandidateJournalData(
            id=1,
            title="Team Meeting",
            content="Same meeting",
            event_date_range_start=base_start + timedelta(days=1),
            event_date_range_end=base_end + timedelta(days=1),
        )

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="Agenda",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[different_day],
        )

        assert result == []
        # Should not call the assessor for different-day journals
        mock_assessor.assess_similarity.assert_not_called()

    async def test_same_day_high_similarity_returns_duplicate(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that high similarity on same day returns DUPLICATE_JOURNAL."""
        mock_assessor.assess_similarity.return_value = 0.9

        existing = CandidateJournalData(
            id=5,
            title="Team Meeting",
            content="Weekly sync",
            event_date_range_start=base_start,
            event_date_range_end=base_end,
        )

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="Weekly sync",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[existing],
        )

        assert len(result) == 1
        assert result[0].journal_id == 5
        assert result[0].reason == ReviewReason.DUPLICATE_JOURNAL
        assert result[0].confidence_score >= 0.6

    async def test_same_day_moderate_similarity_returns_needs_review(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that moderate similarity on same day returns NEEDS_REVIEW."""
        mock_assessor.assess_similarity.return_value = 0.65

        existing = CandidateJournalData(
            id=5,
            title="Weekly Sync",
            content="Discussion topics",
            event_date_range_start=base_start,
            event_date_range_end=base_end,
        )

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="Agenda items",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[existing],
        )

        assert len(result) == 1
        assert result[0].reason == ReviewReason.NEEDS_REVIEW

    async def test_below_threshold_similarity_excluded(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that similarity below threshold produces no candidate."""
        mock_assessor.assess_similarity.return_value = 0.3

        existing = CandidateJournalData(
            id=5,
            title="Completely Different Event",
            content="Nothing related",
            event_date_range_start=base_start,
            event_date_range_end=base_end,
        )

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="Agenda",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[existing],
        )

        assert result == []

    async def test_multiple_candidates_returned_sorted_by_confidence(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that multiple candidates are returned sorted by confidence desc."""
        # Return different scores for different calls
        mock_assessor.assess_similarity.side_effect = [0.7, 0.9, 0.65]

        existing = [
            CandidateJournalData(
                id=1,
                title="Team Meeting v1",
                content="",
                event_date_range_start=base_start,
                event_date_range_end=base_end,
            ),
            CandidateJournalData(
                id=2,
                title="Team Meeting v2",
                content="",
                event_date_range_start=base_start,
                event_date_range_end=base_end,
            ),
            CandidateJournalData(
                id=3,
                title="Team Meeting v3",
                content="",
                event_date_range_start=base_start,
                event_date_range_end=base_end,
            ),
        ]

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=existing,
        )

        assert len(result) == 3
        # Should be sorted by confidence descending
        assert result[0].journal_id == 2  # 0.9
        assert result[1].journal_id == 1  # 0.7
        assert result[2].journal_id == 3  # 0.65

    async def test_mixed_days_only_same_day_assessed(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that only same-day journals are sent to the assessor."""
        mock_assessor.assess_similarity.return_value = 0.8

        existing = [
            CandidateJournalData(
                id=1,
                title="Same Day Event",
                content="",
                event_date_range_start=base_start,
                event_date_range_end=base_end,
            ),
            CandidateJournalData(
                id=2,
                title="Different Day Event",
                content="",
                event_date_range_start=base_start + timedelta(days=1),
                event_date_range_end=base_end + timedelta(days=1),
            ),
        ]

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=existing,
        )

        assert len(result) == 1
        assert result[0].journal_id == 1
        # Assessor called only once (for same-day journal)
        assert mock_assessor.assess_similarity.call_count == 1

    async def test_candidate_includes_details(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that match candidates include relevant details."""
        mock_assessor.assess_similarity.return_value = 0.85

        existing = CandidateJournalData(
            id=5,
            title="Team Meeting",
            content="Weekly sync",
            event_date_range_start=base_start,
            event_date_range_end=base_end,
        )

        result = await detector.detect_candidates(
            incoming_title="Team Meeting Updated",
            incoming_content="Updated agenda",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[existing],
        )

        assert len(result) == 1
        assert "ai_similarity_score" in result[0].details
        assert "candidate_title" in result[0].details

    async def test_same_day_different_time_still_assessed(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that events on the same day but different times are still assessed."""
        mock_assessor.assess_similarity.return_value = 0.8

        # Same day but 3 hours later
        existing = CandidateJournalData(
            id=5,
            title="Team Meeting",
            content="",
            event_date_range_start=base_start + timedelta(hours=3),
            event_date_range_end=base_end + timedelta(hours=3),
        )

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[existing],
        )

        assert len(result) == 1
        mock_assessor.assess_similarity.assert_called_once()

    async def test_assessor_called_with_correct_parameters(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that the assessor is called with correct title, content, and dates."""
        mock_assessor.assess_similarity.return_value = 0.8

        existing = CandidateJournalData(
            id=5,
            title="Existing Meeting",
            content="Existing content",
            event_date_range_start=base_start + timedelta(hours=1),
            event_date_range_end=base_end + timedelta(hours=1),
        )

        await detector.detect_candidates(
            incoming_title="New Meeting",
            incoming_content="New content",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=[existing],
        )

        mock_assessor.assess_similarity.assert_called_once_with(
            title_a="New Meeting",
            content_a="New content",
            start_a=base_start,
            end_a=base_end,
            title_b="Existing Meeting",
            content_b="Existing content",
            start_b=base_start + timedelta(hours=1),
            end_b=base_end + timedelta(hours=1),
        )

    async def test_assessment_error_skips_candidate_processes_rest(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that SimilarityAssessmentError skips the candidate but processes rest."""
        # First call raises parse error, second returns valid score
        mock_assessor.assess_similarity.side_effect = [
            SimilarityAssessmentError("unparseable"),
            0.9,
        ]

        existing = [
            CandidateJournalData(
                id=1,
                title="Event A",
                content="",
                event_date_range_start=base_start,
                event_date_range_end=base_end,
            ),
            CandidateJournalData(
                id=2,
                title="Event B",
                content="",
                event_date_range_start=base_start,
                event_date_range_end=base_end,
            ),
        ]

        result = await detector.detect_candidates(
            incoming_title="Team Meeting",
            incoming_content="",
            incoming_start=base_start,
            incoming_end=base_end,
            existing_journals=existing,
        )

        # First candidate skipped due to parse error, second processed
        assert len(result) == 1
        assert result[0].journal_id == 2

    async def test_transport_error_propagates_for_retry(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
        base_start: datetime,
        base_end: datetime,
    ) -> None:
        """Test that transport/API errors propagate for outbox retry."""
        mock_assessor.assess_similarity.side_effect = ConnectionError(
            "Gemini API unavailable"
        )

        existing = [
            CandidateJournalData(
                id=1,
                title="Event A",
                content="",
                event_date_range_start=base_start,
                event_date_range_end=base_end,
            ),
        ]

        with pytest.raises(ConnectionError, match="Gemini API unavailable"):
            await detector.detect_candidates(
                incoming_title="Team Meeting",
                incoming_content="",
                incoming_start=base_start,
                incoming_end=base_end,
                existing_journals=existing,
            )


@pytest.mark.unit
class TestStravaMatchScenarios:
    """Cross-integration matching scenarios for Strava-sourced journals.

    Tests the specific scenarios called out in the product specification:
    - Strava activity vs existing Google Calendar EVENT journal
    - Multiple Strava activities on the same day (multi-day trip, recording restart)
    - Strava activity with no same-day existing journals
    """

    @pytest.fixture
    def mock_assessor(self) -> AsyncMock:
        return AsyncMock(spec=TitleSimilarityAssessor)

    @pytest.fixture
    def detector(self, mock_assessor: AsyncMock) -> MatchCandidateDetector:
        return MatchCandidateDetector(similarity_assessor=mock_assessor)

    async def test_strava_activity_matches_google_calendar_event(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
    ) -> None:
        """Strava activity should match a Google Calendar EVENT with similar title.

        Product spec scenario: A Strava activity may correspond to a Google
        Calendar event (e.g., 'Saturday Bushwalk'). The match detector should
        flag this as a potential duplicate so the user can merge them.
        """
        mock_assessor.assess_similarity.return_value = 0.88

        google_event_journal = CandidateJournalData(
            id=50,
            title="Saturday Bushwalk",
            content="Bushwalk with the hiking group at Blue Mountains",
            event_date_range_start=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
            event_date_range_end=datetime(2026, 3, 20, 16, 0, tzinfo=UTC),
        )

        candidates = await detector.detect_candidates(
            incoming_title="Saturday Bushwalk",
            incoming_content="Trail through Blue Mountains",
            incoming_start=datetime(2026, 3, 20, 8, 30, tzinfo=UTC),
            incoming_end=datetime(2026, 3, 20, 14, 0, tzinfo=UTC),
            existing_journals=[google_event_journal],
        )

        assert len(candidates) == 1
        assert candidates[0].journal_id == 50
        assert candidates[0].reason == ReviewReason.DUPLICATE_JOURNAL
        assert candidates[0].confidence_score == 0.88
        assert candidates[0].details["candidate_title"] == "Saturday Bushwalk"

    async def test_multi_strava_activity_same_day_recording_restart(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
    ) -> None:
        """Multi-part Strava activities on same day should be flagged.

        Product spec scenario: A hike may be recorded as two Strava activities
        (recording restart). When both import, the second should be flagged as
        a potential match for the first.
        """
        mock_assessor.assess_similarity.return_value = 0.92

        first_part = CandidateJournalData(
            id=60,
            title="Blue Mountains Hike",
            content="Part 1 of the hike",
            event_date_range_start=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
            event_date_range_end=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
        )

        candidates = await detector.detect_candidates(
            incoming_title="Blue Mountains Hike",
            incoming_content="Part 2 of the hike after restart",
            incoming_start=datetime(2026, 3, 20, 12, 30, tzinfo=UTC),
            incoming_end=datetime(2026, 3, 20, 16, 0, tzinfo=UTC),
            existing_journals=[first_part],
        )

        assert len(candidates) == 1
        assert candidates[0].journal_id == 60
        assert candidates[0].reason == ReviewReason.DUPLICATE_JOURNAL

    async def test_strava_activity_no_same_day_existing_journals(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
    ) -> None:
        """Strava activity with no same-day journals should return no candidates.

        The common case: a new activity on a day with no existing journals
        should not create any review items.
        """
        yesterday_journal = CandidateJournalData(
            id=70,
            title="Yesterday's Run",
            content="Easy jog",
            event_date_range_start=datetime(2026, 3, 19, 7, 0, tzinfo=UTC),
            event_date_range_end=datetime(2026, 3, 19, 8, 0, tzinfo=UTC),
        )

        candidates = await detector.detect_candidates(
            incoming_title="Morning Run",
            incoming_content="Easy jog around the park",
            incoming_start=datetime(2026, 3, 20, 7, 0, tzinfo=UTC),
            incoming_end=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
            existing_journals=[yesterday_journal],
        )

        assert candidates == []
        mock_assessor.assess_similarity.assert_not_called()

    async def test_strava_activity_matches_mixed_sources(
        self,
        detector: MatchCandidateDetector,
        mock_assessor: AsyncMock,
    ) -> None:
        """Strava activity should match against journals from multiple sources.

        When there are both Google and Strava journals on the same day,
        matches should be returned for all similar ones.
        """
        mock_assessor.assess_similarity.side_effect = [0.85, 0.3, 0.75]

        google_journal = CandidateJournalData(
            id=80,
            title="Hiking Trip",
            content="Calendar event for the hike",
            event_date_range_start=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
            event_date_range_end=datetime(2026, 3, 20, 14, 0, tzinfo=UTC),
        )
        unrelated_journal = CandidateJournalData(
            id=81,
            title="Dentist Appointment",
            content="Checkup at 3pm",
            event_date_range_start=datetime(2026, 3, 20, 15, 0, tzinfo=UTC),
            event_date_range_end=datetime(2026, 3, 20, 16, 0, tzinfo=UTC),
        )
        strava_journal = CandidateJournalData(
            id=82,
            title="Hiking Trip - Part 1",
            content="First segment",
            event_date_range_start=datetime(2026, 3, 20, 8, 0, tzinfo=UTC),
            event_date_range_end=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
        )

        candidates = await detector.detect_candidates(
            incoming_title="Hiking Trip - Part 2",
            incoming_content="Second segment of the hike",
            incoming_start=datetime(2026, 3, 20, 11, 30, tzinfo=UTC),
            incoming_end=datetime(2026, 3, 20, 14, 0, tzinfo=UTC),
            existing_journals=[google_journal, unrelated_journal, strava_journal],
        )

        # Should find 2 matches (google + strava), skip 1 (dentist)
        assert len(candidates) == 2
        # Sorted by confidence descending
        assert candidates[0].journal_id == 80  # Google: 0.85
        assert candidates[1].journal_id == 82  # Strava: 0.75
