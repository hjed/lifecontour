"""Unit tests for the SnorkellingData entity."""

import pytest
from core_shared.models.journals import SnorkellingData
from core_shared.models.journals.exceptions import SnorkellingDataValidationError


class TestSnorkellingData:
    def test_valid_creation_with_journal_id(self) -> None:
        """Test creating SnorkellingData with a valid journal_id."""
        data = SnorkellingData(journal_id=1)
        assert data.journal_id == 1

    def test_timestamps_default_none(self) -> None:
        """Test that timestamp fields default to None."""
        data = SnorkellingData(journal_id=1)
        assert data.created_at is None
        assert data.updated_at is None

    def test_invalid_journal_id_zero(self) -> None:
        """Test validation fails when journal_id is zero."""
        with pytest.raises(SnorkellingDataValidationError) as exc_info:
            SnorkellingData(journal_id=0)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)

    def test_invalid_journal_id_negative(self) -> None:
        """Test validation fails when journal_id is negative."""
        with pytest.raises(SnorkellingDataValidationError) as exc_info:
            SnorkellingData(journal_id=-1)

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in str(exc_info.value)
