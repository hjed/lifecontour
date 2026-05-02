"""Unit tests for KayakingData entity (KAYAKING type)."""

import pytest
from core_shared.models.journals import KayakingData, KayakingDataValidationError


@pytest.mark.unit
class TestKayakingData:
    """Test KayakingData entity."""

    def test_create_kayaking_data_minimal(self):
        """Test creating kayaking data with only required fields."""
        data = KayakingData(journal_id=1)

        assert data.journal_id == 1
        assert data.water_type is None
        assert data.is_white_water is None
        assert data.rapids_grade is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_kayaking_data_with_water_type(self):
        """Test creating kayaking data with a water type."""
        data = KayakingData(journal_id=1, water_type="river")

        assert data.water_type == "river"

    def test_create_kayaking_data_with_all_fields(self):
        """Test creating kayaking data with all optional fields populated."""
        data = KayakingData(
            journal_id=2,
            water_type="river",
            is_white_water=True,
            rapids_grade="IV",
        )

        assert data.journal_id == 2
        assert data.water_type == "river"
        assert data.is_white_water is True
        assert data.rapids_grade == "IV"

    def test_water_type_river(self):
        """Test creating kayaking data with 'river' water type."""
        data = KayakingData(journal_id=1, water_type="river")
        assert data.water_type == "river"

    def test_water_type_sea(self):
        """Test creating kayaking data with 'sea' water type."""
        data = KayakingData(journal_id=1, water_type="sea")
        assert data.water_type == "sea"

    def test_water_type_lake(self):
        """Test creating kayaking data with 'lake' water type."""
        data = KayakingData(journal_id=1, water_type="lake")
        assert data.water_type == "lake"

    def test_water_type_custom_value(self):
        """Test creating kayaking data with a custom water type value."""
        data = KayakingData(journal_id=1, water_type="estuary")
        assert data.water_type == "estuary"

    def test_water_type_none_is_valid(self):
        """Test that None water_type is valid (field is optional)."""
        data = KayakingData(journal_id=1, water_type=None)
        assert data.water_type is None

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(KayakingDataValidationError) as exc_info:
            KayakingData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(KayakingDataValidationError) as exc_info:
            KayakingData(journal_id=-1)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_water_type_empty_string(self):
        """Test that empty water_type raises validation error."""
        with pytest.raises(KayakingDataValidationError) as exc_info:
            KayakingData(journal_id=1, water_type="")

        assert "water_type" in str(exc_info.value)


@pytest.mark.unit
class TestKayakingDataWhiteWater:
    """Test KayakingData white water fields (is_white_water, rapids_grade)."""

    def test_is_white_water_true(self):
        """Test that is_white_water=True is valid."""
        data = KayakingData(journal_id=1, is_white_water=True)
        assert data.is_white_water is True

    def test_is_white_water_false(self):
        """Test that is_white_water=False is valid."""
        data = KayakingData(journal_id=1, is_white_water=False)
        assert data.is_white_water is False

    def test_is_white_water_none_is_valid(self):
        """Test that is_white_water=None is valid (field is optional)."""
        data = KayakingData(journal_id=1, is_white_water=None)
        assert data.is_white_water is None

    @pytest.mark.parametrize("grade", ["I", "II", "III", "IV", "V", "VI"])
    def test_rapids_grade_valid_values(self, grade: str):
        """Test that all valid rapids grades (I–VI) are accepted."""
        data = KayakingData(journal_id=1, rapids_grade=grade)
        assert data.rapids_grade == grade

    def test_rapids_grade_none_is_valid(self):
        """Test that None rapids_grade is valid (field is optional)."""
        data = KayakingData(journal_id=1, rapids_grade=None)
        assert data.rapids_grade is None

    def test_rapids_grade_invalid_value(self):
        """Test that an invalid rapids grade (e.g. 'VII') raises validation error."""
        with pytest.raises(KayakingDataValidationError) as exc_info:
            KayakingData(journal_id=1, rapids_grade="VII")

        assert "rapids_grade" in str(exc_info.value)

    def test_rapids_grade_empty_string_invalid(self):
        """Test that empty string rapids_grade raises validation error."""
        with pytest.raises(KayakingDataValidationError) as exc_info:
            KayakingData(journal_id=1, rapids_grade="")

        assert "rapids_grade" in str(exc_info.value)

    def test_rapids_grade_invalid_lowercase(self):
        """Test that lowercase grade values are invalid."""
        with pytest.raises(KayakingDataValidationError) as exc_info:
            KayakingData(journal_id=1, rapids_grade="iv")

        assert "rapids_grade" in str(exc_info.value)

    def test_rapids_grade_invalid_numeric(self):
        """Test that numeric string grade values are invalid."""
        with pytest.raises(KayakingDataValidationError) as exc_info:
            KayakingData(journal_id=1, rapids_grade="4")

        assert "rapids_grade" in str(exc_info.value)

    def test_rapids_grade_without_white_water(self):
        """Test that rapids_grade can be set independently of is_white_water."""
        data = KayakingData(journal_id=1, rapids_grade="III")
        assert data.rapids_grade == "III"
        assert data.is_white_water is None

    def test_white_water_with_rapids_grade(self):
        """Test creating data with both white water flag and rapids grade."""
        data = KayakingData(
            journal_id=1,
            is_white_water=True,
            rapids_grade="V",
            water_type="river",
        )
        assert data.is_white_water is True
        assert data.rapids_grade == "V"
        assert data.water_type == "river"
