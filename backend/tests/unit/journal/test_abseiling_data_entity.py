"""Unit tests for AbseilingData entity (ABSEILING_TRIP type)."""

import pytest
from core_shared.models.journals import AbseilingData, AbseilingDataValidationError


@pytest.mark.unit
class TestAbseilingData:
    """Test AbseilingData entity."""

    def test_create_abseiling_data_minimal(self):
        """Test creating abseiling data with only required fields."""
        data = AbseilingData(journal_id=1)

        assert data.journal_id == 1
        assert data.number_of_abseils is None
        assert data.total_length is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_abseiling_data_with_all_fields(self):
        """Test creating abseiling data with all optional fields populated."""
        data = AbseilingData(
            journal_id=5,
            number_of_abseils=3,
            total_length=120,
        )

        assert data.journal_id == 5
        assert data.number_of_abseils == 3
        assert data.total_length == 120

    def test_create_abseiling_data_zero_abseils(self):
        """Test creating abseiling data with zero number_of_abseils (valid: could mean no abseils recorded)."""
        data = AbseilingData(journal_id=1, number_of_abseils=0)

        assert data.number_of_abseils == 0

    def test_create_abseiling_data_zero_length(self):
        """Test creating abseiling data with zero total_length (valid)."""
        data = AbseilingData(journal_id=1, total_length=0)

        assert data.total_length == 0

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(AbseilingDataValidationError) as exc_info:
            AbseilingData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(AbseilingDataValidationError) as exc_info:
            AbseilingData(journal_id=-1)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_number_of_abseils_negative(self):
        """Test that negative number_of_abseils raises validation error."""
        with pytest.raises(AbseilingDataValidationError) as exc_info:
            AbseilingData(journal_id=1, number_of_abseils=-1)

        assert "number_of_abseils" in str(exc_info.value)

    def test_invalid_total_length_negative(self):
        """Test that negative total_length raises validation error."""
        with pytest.raises(AbseilingDataValidationError) as exc_info:
            AbseilingData(journal_id=1, total_length=-5)

        assert "total_length" in str(exc_info.value)

    def test_none_number_of_abseils_is_valid(self):
        """Test that None number_of_abseils is valid (field is optional)."""
        data = AbseilingData(journal_id=1, number_of_abseils=None)

        assert data.number_of_abseils is None

    def test_none_total_length_is_valid(self):
        """Test that None total_length is valid (field is optional)."""
        data = AbseilingData(journal_id=1, total_length=None)

        assert data.total_length is None

    def test_create_abseiling_data_with_aggregate_fields(self):
        """Test creating abseiling data with number_of_setups and number_of_rescues."""
        data = AbseilingData(
            journal_id=1,
            number_of_abseils=5,
            total_length=200,
            number_of_setups=3,
            number_of_rescues=1,
        )

        assert data.number_of_setups == 3
        assert data.number_of_rescues == 1

    def test_invalid_number_of_setups_negative(self):
        """Test that negative number_of_setups raises validation error."""
        with pytest.raises(AbseilingDataValidationError) as exc_info:
            AbseilingData(journal_id=1, number_of_setups=-1)

        assert "number_of_setups" in str(exc_info.value)

    def test_invalid_number_of_rescues_negative(self):
        """Test that negative number_of_rescues raises validation error."""
        with pytest.raises(AbseilingDataValidationError) as exc_info:
            AbseilingData(journal_id=1, number_of_rescues=-2)

        assert "number_of_rescues" in str(exc_info.value)

    def test_none_number_of_setups_is_valid(self):
        """Test that None number_of_setups is valid (field is optional)."""
        data = AbseilingData(journal_id=1, number_of_setups=None)

        assert data.number_of_setups is None

    def test_none_number_of_rescues_is_valid(self):
        """Test that None number_of_rescues is valid (field is optional)."""
        data = AbseilingData(journal_id=1, number_of_rescues=None)

        assert data.number_of_rescues is None

    def test_zero_number_of_setups_is_valid(self):
        """Test that zero number_of_setups is valid."""
        data = AbseilingData(journal_id=1, number_of_setups=0)

        assert data.number_of_setups == 0

    def test_zero_number_of_rescues_is_valid(self):
        """Test that zero number_of_rescues is valid."""
        data = AbseilingData(journal_id=1, number_of_rescues=0)

        assert data.number_of_rescues == 0
