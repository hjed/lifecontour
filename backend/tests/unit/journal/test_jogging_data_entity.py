"""Unit tests for JoggingData entity (JOGGING type)."""

from uuid import UUID, uuid4

import pytest

from app.core.journal.models.exceptions import JoggingDataValidationError
from app.core.journal.models.jogging_data import JoggingData


@pytest.mark.unit
class TestJoggingData:
    """Test JoggingData entity."""

    def test_create_jogging_data_minimal(self):
        """Test creating jogging data with only required fields."""
        data = JoggingData(journal_id=1)

        assert data.journal_id == 1
        assert data.route_id is None
        assert data.pace is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_jogging_data_with_route(self):
        """Test creating jogging data with a route ID."""
        route_id = uuid4()
        data = JoggingData(journal_id=1, route_id=route_id)

        assert data.route_id == route_id

    def test_create_jogging_data_with_pace(self):
        """Test creating jogging data with a pace value."""
        # 5 minutes per km = 300 seconds per km
        data = JoggingData(journal_id=1, pace=300)

        assert data.pace == 300

    def test_create_jogging_data_with_all_fields(self):
        """Test creating jogging data with all fields populated."""
        route_id = uuid4()
        data = JoggingData(
            journal_id=2,
            route_id=route_id,
            pace=360,  # 6 min/km
        )

        assert data.journal_id == 2
        assert data.route_id == route_id
        assert data.pace == 360

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(JoggingDataValidationError) as exc_info:
            JoggingData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(JoggingDataValidationError) as exc_info:
            JoggingData(journal_id=-3)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_pace_negative(self):
        """Test that negative pace raises validation error."""
        with pytest.raises(JoggingDataValidationError) as exc_info:
            JoggingData(journal_id=1, pace=-1)

        assert "pace" in str(exc_info.value)

    def test_zero_pace_is_valid(self):
        """Test that zero pace is valid (non-negative constraint)."""
        data = JoggingData(journal_id=1, pace=0)

        assert data.pace == 0

    def test_none_pace_is_valid(self):
        """Test that None pace is valid (field is optional)."""
        data = JoggingData(journal_id=1, pace=None)

        assert data.pace is None

    def test_none_route_id_is_valid(self):
        """Test that None route_id is valid (field is optional)."""
        data = JoggingData(journal_id=1, route_id=None)

        assert data.route_id is None

    def test_route_id_is_uuid(self):
        """Test that route_id must be a UUID."""
        route_id = UUID("12345678-1234-5678-1234-567812345678")
        data = JoggingData(journal_id=1, route_id=route_id)

        assert isinstance(data.route_id, UUID)

    def test_large_valid_pace(self):
        """Test that a large pace value (slow runner) is valid."""
        # 15 minutes per km = 900 seconds per km
        data = JoggingData(journal_id=1, pace=900)

        assert data.pace == 900
