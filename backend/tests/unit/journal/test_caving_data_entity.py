"""Unit tests for the CavingData entity."""

import pytest
from core_shared.models.journals import CavingData
from core_shared.models.journals.exceptions import CavingDataValidationError


class TestCavingData:
    def test_valid_creation_all_fields(self) -> None:
        """Test creating CavingData with all fields provided."""
        data = CavingData(
            journal_id=1,
            template_id="123e4567-e89b-12d3-a456-426614174000",
            is_vertical=True,
            is_horizontal=False,
        )
        assert data.journal_id == 1
        assert data.template_id == "123e4567-e89b-12d3-a456-426614174000"
        assert data.is_vertical is True
        assert data.is_horizontal is False

    def test_valid_creation_only_required(self) -> None:
        """Test creating CavingData with only required fields."""
        data = CavingData(journal_id=1)
        assert data.journal_id == 1
        assert data.template_id is None
        assert data.is_vertical is None
        assert data.is_horizontal is None

    def test_invalid_journal_id_zero(self) -> None:
        """Test validation fails when journal_id is zero."""
        with pytest.raises(CavingDataValidationError) as exc_info:
            CavingData(journal_id=0)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)

    def test_invalid_journal_id_negative(self) -> None:
        """Test validation fails when journal_id is negative."""
        with pytest.raises(CavingDataValidationError) as exc_info:
            CavingData(journal_id=-1)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)
