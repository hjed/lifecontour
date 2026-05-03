"""Unit tests for the DownhillSkiingData entity."""

import pytest
from core_shared.models.journals import DownhillSkiingData
from core_shared.models.journals.exceptions import DownhillSkiingDataValidationError


class TestDownhillSkiingData:
    def test_valid_creation_with_journal_id(self) -> None:
        """Test creating DownhillSkiingData with a valid journal_id."""
        data = DownhillSkiingData(journal_id=1)
        assert data.journal_id == 1

    def test_timestamps_default_none(self) -> None:
        """Test that timestamp fields default to None."""
        data = DownhillSkiingData(journal_id=1)
        assert data.created_at is None
        assert data.updated_at is None

    def test_invalid_journal_id_zero(self) -> None:
        """Test validation fails when journal_id is zero."""
        with pytest.raises(DownhillSkiingDataValidationError) as exc_info:
            DownhillSkiingData(journal_id=0)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)

    def test_invalid_journal_id_negative(self) -> None:
        """Test validation fails when journal_id is negative."""
        with pytest.raises(DownhillSkiingDataValidationError) as exc_info:
            DownhillSkiingData(journal_id=-1)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)
