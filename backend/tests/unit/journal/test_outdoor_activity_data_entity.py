"""Unit tests for OutdoorActivityData entity (OUTDOOR_ACTIVITY type)."""

import pytest

from app.core.journal.models.exceptions import OutdoorActivityDataValidationError
from app.core.journal.models.outdoor_activity_data import OutdoorActivityData


@pytest.mark.unit
class TestOutdoorActivityData:
    """Test OutdoorActivityData entity."""

    def test_create_outdoor_activity_data_minimal(self):
        """Test creating outdoor activity data with only required fields."""
        data = OutdoorActivityData(journal_id=1)

        assert data.journal_id == 1
        assert data.activity_type is None
        assert data.weather_conditions is None
        assert data.role is None
        assert data.in_leadership_role is None
        assert data.participant_notes is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_outdoor_activity_data_with_activity_type(self):
        """Test creating outdoor activity data with an activity type."""
        data = OutdoorActivityData(journal_id=1, activity_type="Hiking")

        assert data.activity_type == "Hiking"

    def test_create_outdoor_activity_data_with_weather(self):
        """Test creating outdoor activity data with weather conditions."""
        data = OutdoorActivityData(journal_id=1, weather_conditions="Sunny, 22°C")

        assert data.weather_conditions == "Sunny, 22°C"

    def test_create_outdoor_activity_data_with_role(self):
        """Test creating outdoor activity data with a role."""
        data = OutdoorActivityData(journal_id=1, role="Participant")

        assert data.role == "Participant"

    def test_create_outdoor_activity_data_with_leadership_role(self):
        """Test creating outdoor activity data with leadership role flag."""
        data = OutdoorActivityData(journal_id=1, in_leadership_role=True)

        assert data.in_leadership_role is True

    def test_create_outdoor_activity_data_with_participant_notes(self):
        """Test creating outdoor activity data with participant notes."""
        data = OutdoorActivityData(journal_id=1, participant_notes="Great hike!")

        assert data.participant_notes == "Great hike!"

    def test_create_outdoor_activity_data_with_all_fields(self):
        """Test creating outdoor activity data with all fields populated."""
        data = OutdoorActivityData(
            journal_id=5,
            activity_type="Bushwalking",
            weather_conditions="Overcast, mild",
            role="Leader",
            in_leadership_role=True,
            participant_notes="Led group of 8 through the national park",
        )

        assert data.journal_id == 5
        assert data.activity_type == "Bushwalking"
        assert data.weather_conditions == "Overcast, mild"
        assert data.role == "Leader"
        assert data.in_leadership_role is True
        assert data.participant_notes == "Led group of 8 through the national park"

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=-1)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_activity_type_empty(self):
        """Test that empty activity_type raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, activity_type="")

        assert "activity_type" in str(exc_info.value)

    def test_invalid_activity_type_too_long(self):
        """Test that activity_type exceeding max length raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, activity_type="A" * 101)

        assert "activity_type" in str(exc_info.value)

    def test_invalid_weather_conditions_empty(self):
        """Test that empty weather_conditions raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, weather_conditions="")

        assert "weather_conditions" in str(exc_info.value)

    def test_invalid_weather_conditions_too_long(self):
        """Test that weather_conditions exceeding max length raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, weather_conditions="A" * 201)

        assert "weather_conditions" in str(exc_info.value)

    def test_invalid_role_empty(self):
        """Test that empty role raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, role="")

        assert "role" in str(exc_info.value)

    def test_invalid_role_too_long(self):
        """Test that role exceeding max length raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, role="A" * 101)

        assert "role" in str(exc_info.value)

    def test_invalid_participant_notes_empty(self):
        """Test that empty participant_notes raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, participant_notes="")

        assert "participant_notes" in str(exc_info.value)

    def test_invalid_participant_notes_too_long(self):
        """Test that participant_notes exceeding max length raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, participant_notes="A" * 2001)

        assert "participant_notes" in str(exc_info.value)

    def test_activity_type_whitespace_only_invalid(self):
        """Test that whitespace-only activity_type raises validation error."""
        with pytest.raises(OutdoorActivityDataValidationError) as exc_info:
            OutdoorActivityData(journal_id=1, activity_type="   ")

        assert "activity_type" in str(exc_info.value)
