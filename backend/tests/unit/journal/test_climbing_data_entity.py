"""Unit tests for ClimbingData entity (CLIMBING type)."""

import pytest
from core_shared.models.journals import ClimbingData, ClimbingDataValidationError


@pytest.mark.unit
class TestClimbingData:
    """Test ClimbingData entity."""

    def test_create_climbing_data_minimal(self):
        """Test creating climbing data with only required fields."""
        data = ClimbingData(journal_id=1)

        assert data.journal_id == 1
        assert data.climbing_type is None
        assert data.grade is None
        assert data.length is None
        assert data.indoor is False
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_climbing_data_with_all_fields(self):
        """Test creating climbing data with all optional fields populated."""
        data = ClimbingData(
            journal_id=2,
            climbing_type="sport",
            grade=18,
            length=25,
        )

        assert data.journal_id == 2
        assert data.climbing_type == "sport"
        assert data.grade == 18
        assert data.length == 25

    def test_climbing_type_sport(self):
        """Test creating climbing data with 'sport' climbing type."""
        data = ClimbingData(journal_id=1, climbing_type="sport")
        assert data.climbing_type == "sport"

    def test_climbing_type_trad(self):
        """Test creating climbing data with 'trad' climbing type."""
        data = ClimbingData(journal_id=1, climbing_type="trad")
        assert data.climbing_type == "trad"

    def test_climbing_type_bouldering(self):
        """Test creating climbing data with 'bouldering' climbing type."""
        data = ClimbingData(journal_id=1, climbing_type="bouldering")
        assert data.climbing_type == "bouldering"

    def test_climbing_type_top_rope(self):
        """Test creating climbing data with 'top_rope' climbing type."""
        data = ClimbingData(journal_id=1, climbing_type="top_rope")
        assert data.climbing_type == "top_rope"

    def test_indoor_defaults_to_false(self):
        """Test that indoor defaults to False when not provided."""
        data = ClimbingData(journal_id=1)
        assert data.indoor is False

    def test_indoor_true(self):
        """Test that indoor can be set to True."""
        data = ClimbingData(journal_id=1, indoor=True)
        assert data.indoor is True

    def test_indoor_is_independent_of_climbing_type(self):
        """Indoor is a separate flag, combinable with any climbing type."""
        data = ClimbingData(journal_id=1, climbing_type="sport", indoor=True)
        assert data.climbing_type == "sport"
        assert data.indoor is True

    def test_invalid_indoor_non_bool(self):
        """Test that a non-boolean indoor raises validation error."""
        with pytest.raises(ClimbingDataValidationError) as exc_info:
            ClimbingData(journal_id=1, indoor="yes")  # type: ignore[arg-type]

        assert "indoor" in str(exc_info.value)

    def test_climbing_type_none_is_valid(self):
        """Test that None climbing_type is valid (field is optional)."""
        data = ClimbingData(journal_id=1, climbing_type=None)
        assert data.climbing_type is None

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(ClimbingDataValidationError) as exc_info:
            ClimbingData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(ClimbingDataValidationError) as exc_info:
            ClimbingData(journal_id=-2)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_climbing_type(self):
        """Test that an unrecognised climbing type raises validation error."""
        with pytest.raises(ClimbingDataValidationError) as exc_info:
            ClimbingData(journal_id=1, climbing_type="free_solo")

        assert "climbing_type" in str(exc_info.value)

    def test_invalid_climbing_type_empty_string(self):
        """Test that empty climbing type raises validation error."""
        with pytest.raises(ClimbingDataValidationError) as exc_info:
            ClimbingData(journal_id=1, climbing_type="")

        assert "climbing_type" in str(exc_info.value)

    def test_invalid_grade_negative(self):
        """Test that negative grade raises validation error."""
        with pytest.raises(ClimbingDataValidationError) as exc_info:
            ClimbingData(journal_id=1, grade=-1)

        assert "grade" in str(exc_info.value)

    def test_grade_zero_is_valid(self):
        """Test that grade of 0 is valid."""
        data = ClimbingData(journal_id=1, grade=0)
        assert data.grade == 0

    def test_invalid_length_negative(self):
        """Test that negative length raises validation error."""
        with pytest.raises(ClimbingDataValidationError) as exc_info:
            ClimbingData(journal_id=1, length=-10)

        assert "length" in str(exc_info.value)

    def test_length_zero_is_valid(self):
        """Test that length of 0 is valid."""
        data = ClimbingData(journal_id=1, length=0)
        assert data.length == 0
