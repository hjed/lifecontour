"""Unit tests for AttendanceTransitionService.

Tests transition eligibility, idempotency, batch boundaries, and status filtering
using mock repositories to isolate service logic.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus

from app.core.journal.services.attendance_transition_service import (
    AttendanceTransitionService,
    TransitionResult,
)


def _make_relationship(
    journal_id: int = 1,
    contact_id: int = 100,
    status: AttendeeStatus = AttendeeStatus.ATTENDING,
    relationship_type: JournalContactRelationshipType = JournalContactRelationshipType.PARTICIPANT,
) -> JournalContactRelationship:
    """Build a JournalContactRelationship for testing."""
    return JournalContactRelationship(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=relationship_type,
        status=status,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Create a mock JournalContactRelationshipRepository."""
    repo = MagicMock()
    repo.find_attending_for_past_events = AsyncMock(return_value=[])
    repo.update_status = AsyncMock()
    return repo


@pytest.fixture
def service(mock_repo: MagicMock) -> AttendanceTransitionService:
    """Create an AttendanceTransitionService with a mock repo."""
    return AttendanceTransitionService(mock_repo)


@pytest.mark.unit
class TestAttendanceTransitionEligibility:
    """Tests for transition eligibility logic."""

    async def test_transitions_attending_contacts_on_past_events(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """ATTENDING contacts on past events are transitioned to ATTENDED."""
        eligible = [
            _make_relationship(journal_id=1, contact_id=100),
            _make_relationship(journal_id=2, contact_id=200),
        ]
        mock_repo.find_attending_for_past_events.return_value = eligible

        cutoff = datetime.now(UTC)
        result = await service.transition_past_event_attendees(cutoff)

        assert result.transitioned_count == 2
        assert mock_repo.update_status.call_count == 2
        # Verify each call was made with ATTENDED
        for call in mock_repo.update_status.call_args_list:
            args = call[1] if call[1] else {}
            if args:
                assert args.get("status") == AttendeeStatus.ATTENDED
            else:
                # Positional args
                assert call[0][3] == AttendeeStatus.ATTENDED

    async def test_empty_result_when_no_eligible_rows(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """No eligible rows returns zero transitions."""
        mock_repo.find_attending_for_past_events.return_value = []

        cutoff = datetime.now(UTC)
        result = await service.transition_past_event_attendees(cutoff)

        assert result.transitioned_count == 0
        mock_repo.update_status.assert_not_called()

    async def test_passes_cutoff_time_to_repository(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """The cutoff time is passed correctly to the repository query."""
        cutoff = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        await service.transition_past_event_attendees(cutoff, batch_size=50)

        mock_repo.find_attending_for_past_events.assert_called_once_with(
            cutoff_time=cutoff, batch_size=50
        )


@pytest.mark.unit
class TestAttendanceTransitionIdempotency:
    """Tests for idempotency of the transition job."""

    async def test_second_run_finds_no_eligible_rows(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """After first transition, re-running produces zero transitions."""
        # First run: 2 eligible
        mock_repo.find_attending_for_past_events.return_value = [
            _make_relationship(journal_id=1, contact_id=100),
            _make_relationship(journal_id=2, contact_id=200),
        ]
        cutoff = datetime.now(UTC)
        result1 = await service.transition_past_event_attendees(cutoff)
        assert result1.transitioned_count == 2

        # Second run: no eligible (already transitioned)
        mock_repo.find_attending_for_past_events.return_value = []
        result2 = await service.transition_past_event_attendees(cutoff)
        assert result2.transitioned_count == 0

    async def test_already_attended_not_re_transitioned(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """Contacts already ATTENDED are not returned by the repository query.

        The repository's find_attending_for_past_events only returns ATTENDING,
        so ATTENDED contacts are inherently excluded.
        """
        mock_repo.find_attending_for_past_events.return_value = []

        cutoff = datetime.now(UTC)
        result = await service.transition_past_event_attendees(cutoff)

        assert result.transitioned_count == 0
        mock_repo.update_status.assert_not_called()


@pytest.mark.unit
class TestAttendanceTransitionStatusFiltering:
    """Tests verifying that non-ATTENDING statuses are untouched."""

    async def test_only_attending_status_is_transitioned(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """The repository query only returns ATTENDING contacts.

        MAYBE, DECLINED, NO_REPLY, and ATTENDED are excluded at the query level.
        The service trusts the repository filter — this test verifies the service
        correctly calls update_status for every row returned.
        """
        # Only ATTENDING contacts are returned by the repo
        attending = _make_relationship(journal_id=1, contact_id=100)
        mock_repo.find_attending_for_past_events.return_value = [attending]

        cutoff = datetime.now(UTC)
        result = await service.transition_past_event_attendees(cutoff)

        assert result.transitioned_count == 1
        mock_repo.update_status.assert_called_once()


@pytest.mark.unit
class TestAttendanceTransitionBatchBoundary:
    """Tests for batch processing boundaries."""

    async def test_batch_size_limits_processing(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """When batch_size is set, only that many rows are processed per call."""
        # Simulate exactly batch_size rows returned
        batch_size = 3
        eligible = [
            _make_relationship(journal_id=i + 1, contact_id=(i + 1) * 100)
            for i in range(batch_size)
        ]
        mock_repo.find_attending_for_past_events.return_value = eligible

        cutoff = datetime.now(UTC)
        result = await service.transition_past_event_attendees(
            cutoff, batch_size=batch_size
        )

        assert result.transitioned_count == batch_size
        mock_repo.find_attending_for_past_events.assert_called_once_with(
            cutoff_time=cutoff, batch_size=batch_size
        )

    async def test_default_batch_size(
        self, service: AttendanceTransitionService, mock_repo: MagicMock
    ):
        """Default batch_size is 100."""
        cutoff = datetime.now(UTC)
        await service.transition_past_event_attendees(cutoff)

        mock_repo.find_attending_for_past_events.assert_called_once_with(
            cutoff_time=cutoff, batch_size=100
        )


@pytest.mark.unit
class TestTransitionResult:
    """Tests for the TransitionResult dataclass."""

    def test_transition_result_fields(self):
        """TransitionResult has expected fields."""
        result = TransitionResult(transitioned_count=5)
        assert result.transitioned_count == 5

    def test_transition_result_zero(self):
        """TransitionResult with zero transitions."""
        result = TransitionResult(transitioned_count=0)
        assert result.transitioned_count == 0
