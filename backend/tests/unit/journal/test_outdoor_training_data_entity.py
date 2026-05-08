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


def test_invalid_focus_areas_empty_string():
    """Test validation fails for empty string in focus_areas."""
    with pytest.raises(OutdoorTrainingDataValidationError) as exc_info:
        OutdoorTrainingData(journal_id=1, focus_areas=[""])

    assert "focus_areas" in str(exc_info.value)
    assert "Focus areas must be non-empty strings" in str(exc_info.value)


def test_invalid_focus_areas_whitespace():
    """Test validation fails for whitespace string in focus_areas."""
    with pytest.raises(OutdoorTrainingDataValidationError) as exc_info:
        OutdoorTrainingData(journal_id=1, focus_areas=["   "])

    assert "focus_areas" in str(exc_info.value)
    assert "Focus areas must be non-empty strings" in str(exc_info.value)


def test_invalid_focus_areas_type():
    """Test validation fails for non-string type in focus_areas."""
    with pytest.raises(OutdoorTrainingDataValidationError) as exc_info:
        # ignore type checking intentionally to test runtime validation
        OutdoorTrainingData(journal_id=1, focus_areas=[123])  # type: ignore

    assert "focus_areas" in str(exc_info.value)
    assert "Focus areas must be non-empty strings" in str(exc_info.value)
