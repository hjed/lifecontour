"""Unit tests for CrossCountrySkiingData entity (CROSS_COUNTRY_SKIING type)."""

from uuid import UUID, uuid4

import pytest

from app.core.journal.models.cross_country_skiing_data import CrossCountrySkiingData
from app.core.journal.models.exceptions import CrossCountrySkiingDataValidationError


@pytest.mark.unit
class TestCrossCountrySkiingData:
    """Test CrossCountrySkiingData entity."""

    def test_create_skiing_data_minimal(self):
        """Test creating skiing data with only required fields."""
        data = CrossCountrySkiingData(journal_id=1)

        assert data.journal_id == 1
        assert data.route_id is None
        assert data.snow_conditions is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_skiing_data_with_route(self):
        """Test creating skiing data with a route ID."""
        route_id = uuid4()
        data = CrossCountrySkiingData(journal_id=1, route_id=route_id)

        assert data.route_id == route_id

    def test_create_skiing_data_with_snow_conditions(self):
        """Test creating skiing data with snow conditions."""
        data = CrossCountrySkiingData(journal_id=1, snow_conditions="packed powder")

        assert data.snow_conditions == "packed powder"

    def test_create_skiing_data_with_all_fields(self):
        """Test creating skiing data with all optional fields populated."""
        route_id = uuid4()
        data = CrossCountrySkiingData(
            journal_id=2,
            route_id=route_id,
            snow_conditions="groomed trails",
        )

        assert data.journal_id == 2
        assert data.route_id == route_id
        assert data.snow_conditions == "groomed trails"

    def test_snow_conditions_various_values(self):
        """Test creating skiing data with various snow condition descriptions."""
        for conditions in ["fresh powder", "icy", "wet snow", "groomed", "crusty"]:
            data = CrossCountrySkiingData(journal_id=1, snow_conditions=conditions)
            assert data.snow_conditions == conditions

    def test_snow_conditions_none_is_valid(self):
        """Test that None snow_conditions is valid (field is optional)."""
        data = CrossCountrySkiingData(journal_id=1, snow_conditions=None)
        assert data.snow_conditions is None

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(CrossCountrySkiingDataValidationError) as exc_info:
            CrossCountrySkiingData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(CrossCountrySkiingDataValidationError) as exc_info:
            CrossCountrySkiingData(journal_id=-5)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_snow_conditions_empty_string(self):
        """Test that empty snow_conditions raises validation error."""
        with pytest.raises(CrossCountrySkiingDataValidationError) as exc_info:
            CrossCountrySkiingData(journal_id=1, snow_conditions="")

        assert "snow_conditions" in str(exc_info.value)

    def test_route_id_is_uuid(self):
        """Test that route_id must be a UUID."""
        route_id = UUID("12345678-1234-5678-1234-567812345678")
        data = CrossCountrySkiingData(journal_id=1, route_id=route_id)

        assert isinstance(data.route_id, UUID)
