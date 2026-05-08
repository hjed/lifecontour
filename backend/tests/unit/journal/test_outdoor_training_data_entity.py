import pytest
from core_shared.models.journals import (
    OutdoorActivitySubtype,
    OutdoorTrainingData,
    OutdoorTrainingDataValidationError,
)


def test_valid_outdoor_training_data():
    """Test creating a valid OutdoorTrainingData entity."""
    data = OutdoorTrainingData(
        journal_id=1,
        focus_areas=[
            OutdoorActivitySubtype.CANYONING.value,
            "Wilderness First Aid",
        ],
    )

    assert data.journal_id == 1
    assert data.focus_areas == ["canyoning", "Wilderness First Aid"]


def test_invalid_journal_id():
    """Test validation fails for invalid journal ID."""
    with pytest.raises(OutdoorTrainingDataValidationError) as exc_info:
        OutdoorTrainingData(journal_id=-1)

    assert "journal_id" in str(exc_info.value)
