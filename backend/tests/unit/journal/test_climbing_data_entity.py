"""Unit tests for ClimbingData entity (CLIMBING type)."""

from uuid import UUID

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
        assert data.template_id is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_climbing_data_with_all_fields(self):
        """Test creating climbing data with all optional fields populated."""
        template_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        data = ClimbingData(
            journal_id=2,
            climbing_type="sport",
            grade=18,
            length=25,
            template_id=template_uuid,
        )

        assert data.journal_id == 2
        assert data.climbing_type == "sport"
        assert data.grade == 18
        assert data.length == 25
        assert str(data.template_id) == template_uuid

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

    def test_template_id_none_is_valid(self):
        """Test that None template_id is valid (field is optional)."""
        data = ClimbingData(journal_id=1, template_id=None)
        assert data.template_id is None

    def test_template_id_uuid_object_is_valid(self):
        """Test that a UUID object is accepted as template_id."""
        uuid_val = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        data = ClimbingData(journal_id=1, template_id=uuid_val)
        assert data.template_id == uuid_val

    def test_template_id_string_uuid_is_valid(self):
        """Test that a string UUID is accepted as template_id."""
        uuid_str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        data = ClimbingData(journal_id=1, template_id=uuid_str)
        assert str(data.template_id) == uuid_str
