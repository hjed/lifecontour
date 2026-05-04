import pytest
from core_shared.models.journals import (
    OutdoorActivitySubtype,
    OutdoorPlanningData,
    OutdoorPlanningDataValidationError,
)


def test_valid_outdoor_planning_data():
    """Test creating a valid OutdoorPlanningData entity."""
    data = OutdoorPlanningData(
        journal_id=1,
        topics="Discussed the upcoming trip to Blue Mountains.",
        activity_types=[
            OutdoorActivitySubtype.CANYONING,
            OutdoorActivitySubtype.BUSHWALKING,
        ],
    )

    assert data.journal_id == 1
    assert data.topics == "Discussed the upcoming trip to Blue Mountains."
    assert data.activity_types == ["canyoning", "bushwalking"]


def test_invalid_journal_id():
    """Test validation fails for invalid journal ID."""
    with pytest.raises(OutdoorPlanningDataValidationError) as exc_info:
        OutdoorPlanningData(journal_id=-1)

    assert "journal_id" in str(exc_info.value)


def test_invalid_activity_types():
    """Test validation fails for invalid activity types."""
    with pytest.raises(OutdoorPlanningDataValidationError) as exc_info:
        OutdoorPlanningData(journal_id=1, activity_types=["invalid_type"])

    assert "activity_types" in str(exc_info.value)
    assert "invalid_type" in str(exc_info.value)
