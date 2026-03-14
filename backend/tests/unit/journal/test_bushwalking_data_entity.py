"""Unit tests for BushwalkingData entity (BUSHWALKING type)."""

from uuid import UUID, uuid4

import pytest
from core_shared.models.journals import BushwalkingData, BushwalkingDataValidationError


@pytest.mark.unit
class TestBushwalkingData:
    """Test BushwalkingData entity."""

    def test_create_bushwalking_data_minimal(self):
        """Test creating bushwalking data with only required fields."""
        data = BushwalkingData(journal_id=1)

        assert data.journal_id == 1
        assert data.route_id is None
        assert data.track_grading is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_bushwalking_data_with_route(self):
        """Test creating bushwalking data with a route ID."""
        route_id = uuid4()
        data = BushwalkingData(journal_id=1, route_id=route_id)

        assert data.route_id == route_id

    def test_create_bushwalking_data_grade_1(self):
        """Test creating bushwalking data with Grade 1 track grading."""
        data = BushwalkingData(journal_id=1, track_grading="Grade 1")

        assert data.track_grading == "Grade 1"

    def test_create_bushwalking_data_grade_2(self):
        """Test creating bushwalking data with Grade 2 track grading."""
        data = BushwalkingData(journal_id=1, track_grading="Grade 2")

        assert data.track_grading == "Grade 2"

    def test_create_bushwalking_data_grade_3(self):
        """Test creating bushwalking data with Grade 3 track grading."""
        data = BushwalkingData(journal_id=1, track_grading="Grade 3")

        assert data.track_grading == "Grade 3"

    def test_create_bushwalking_data_grade_4(self):
        """Test creating bushwalking data with Grade 4 track grading."""
        data = BushwalkingData(journal_id=1, track_grading="Grade 4")

        assert data.track_grading == "Grade 4"

    def test_create_bushwalking_data_grade_5(self):
        """Test creating bushwalking data with Grade 5 track grading."""
        data = BushwalkingData(journal_id=1, track_grading="Grade 5")

        assert data.track_grading == "Grade 5"

    def test_create_bushwalking_data_with_all_fields(self):
        """Test creating bushwalking data with all fields populated."""
        route_id = uuid4()
        data = BushwalkingData(
            journal_id=3,
            route_id=route_id,
            track_grading="Grade 3",
        )

        assert data.journal_id == 3
        assert data.route_id == route_id
        assert data.track_grading == "Grade 3"

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(BushwalkingDataValidationError) as exc_info:
            BushwalkingData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(BushwalkingDataValidationError) as exc_info:
            BushwalkingData(journal_id=-5)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_track_grading_unknown_value(self):
        """Test that an unrecognised track grading raises validation error."""
        with pytest.raises(BushwalkingDataValidationError) as exc_info:
            BushwalkingData(journal_id=1, track_grading="Grade 6")

        assert "track_grading" in str(exc_info.value)

    def test_invalid_track_grading_empty_string(self):
        """Test that an empty track grading string raises validation error."""
        with pytest.raises(BushwalkingDataValidationError) as exc_info:
            BushwalkingData(journal_id=1, track_grading="")

        assert "track_grading" in str(exc_info.value)

    def test_invalid_track_grading_numeric(self):
        """Test that a bare numeric track grading raises validation error."""
        with pytest.raises(BushwalkingDataValidationError) as exc_info:
            BushwalkingData(journal_id=1, track_grading="3")

        assert "track_grading" in str(exc_info.value)

    def test_none_track_grading_is_valid(self):
        """Test that None track_grading is valid (field is optional)."""
        data = BushwalkingData(journal_id=1, track_grading=None)

        assert data.track_grading is None

    def test_route_id_is_uuid(self):
        """Test that route_id must be a UUID."""
        route_id = UUID("12345678-1234-5678-1234-567812345678")
        data = BushwalkingData(journal_id=1, route_id=route_id)

        assert isinstance(data.route_id, UUID)
