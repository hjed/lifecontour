"""Unit tests for the CanoeingData entity."""

import pytest
from core_shared.models.journals import CanoeingData
from core_shared.models.journals.exceptions import CanoeingDataValidationError


class TestCanoeingData:
    def test_valid_creation_all_fields(self) -> None:
        """Test creating CanoeingData with all fields provided."""
        data = CanoeingData(
            journal_id=1,
            water_type="river",
        )
        assert data.journal_id == 1
        assert data.water_type == "river"

    def test_valid_creation_only_required(self) -> None:
        """Test creating CanoeingData with only required fields."""
        data = CanoeingData(journal_id=1)
        assert data.journal_id == 1
        assert data.water_type is None

    def test_valid_water_type_values(self) -> None:
        """Test that water_type accepts various string values."""
        for water_type in ["river", "lake", "sea"]:
            data = CanoeingData(journal_id=1, water_type=water_type)
            assert data.water_type == water_type

    def test_water_type_none(self) -> None:
        """Test that water_type can be None."""
        data = CanoeingData(journal_id=1, water_type=None)
        assert data.water_type is None

    def test_timestamps_default_none(self) -> None:
        """Test that timestamp fields default to None."""
        data = CanoeingData(journal_id=1)
        assert data.created_at is None
        assert data.updated_at is None

    def test_invalid_journal_id_zero(self) -> None:
        """Test validation fails when journal_id is zero."""
        with pytest.raises(CanoeingDataValidationError) as exc_info:
            CanoeingData(journal_id=0)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)

    def test_invalid_journal_id_negative(self) -> None:
        """Test validation fails when journal_id is negative."""
        with pytest.raises(CanoeingDataValidationError) as exc_info:
            CanoeingData(journal_id=-1)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)

    def test_invalid_water_type_empty(self) -> None:
        """Test validation fails when water_type is an empty string."""
        with pytest.raises(CanoeingDataValidationError) as exc_info:
            CanoeingData(journal_id=1, water_type="   ")

        assert exc_info.value.field == "water_type"
        assert "empty string" in str(exc_info.value)
