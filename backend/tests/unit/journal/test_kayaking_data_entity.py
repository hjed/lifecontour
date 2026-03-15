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
            water_type="sea",
        )

        assert data.journal_id == 2
        assert data.water_type == "sea"

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
