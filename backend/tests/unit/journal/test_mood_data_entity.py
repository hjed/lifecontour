"""Unit tests for MoodData entity (MOOD_RATING type)."""

import pytest

from app.core.journal.models.constants import (
    MAX_ENERGY_LEVEL,
    MAX_MOOD_LABEL_LENGTH,
    MAX_MOOD_VALUE,
    MIN_ENERGY_LEVEL,
    MIN_MOOD_VALUE,
)
from app.core.journal.models.exceptions import MoodDataValidationError
from app.core.journal.models.mood_data import MoodData


@pytest.mark.unit
class TestMoodData:
    """Test MoodData entity."""

    def test_create_mood_data_minimal(self):
        """Test creating mood data with minimal required fields."""
        mood_data = MoodData(journal_id=1)

        assert mood_data.journal_id == 1
        assert mood_data.mood_value is None
        assert mood_data.mood_label is None
        assert mood_data.energy_level is None

    def test_create_mood_data_with_mood_value(self):
        """Test creating mood data with mood value."""
        mood_data = MoodData(journal_id=1, mood_value=7)

        assert mood_data.mood_value == 7
        assert mood_data.has_mood_data is True

    def test_create_mood_data_with_mood_label(self):
        """Test creating mood data with mood label."""
        mood_data = MoodData(journal_id=1, mood_label="happy")

        assert mood_data.mood_label == "happy"
        assert mood_data.has_mood_data is True

    def test_create_mood_data_with_energy_level(self):
        """Test creating mood data with energy level."""
        mood_data = MoodData(journal_id=1, energy_level=8)

        assert mood_data.energy_level == 8
        assert mood_data.has_energy_data is True

    def test_create_mood_data_complete(self):
        """Test creating mood data with all fields."""
        mood_data = MoodData(
            journal_id=1,
            mood_value=7,
            mood_label="content",
            energy_level=6,
        )

        assert mood_data.mood_value == 7
        assert mood_data.mood_label == "content"
        assert mood_data.energy_level == 6
        assert mood_data.has_mood_data is True
        assert mood_data.has_energy_data is True


@pytest.mark.unit
class TestMoodDataValidation:
    """Test MoodData validation."""

    def test_invalid_journal_id_raises_error(self):
        """Test that invalid journal_id raises error."""
        with pytest.raises(
            MoodDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            MoodData(journal_id=0)

        with pytest.raises(
            MoodDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            MoodData(journal_id=-1)


@pytest.mark.unit
class TestMoodDataMoodValueValidation:
    """Test MoodData mood_value validation."""

    def test_mood_value_at_min(self):
        """Test mood value at minimum is valid."""
        mood_data = MoodData(journal_id=1, mood_value=MIN_MOOD_VALUE)
        assert mood_data.mood_value == MIN_MOOD_VALUE

    def test_mood_value_at_max(self):
        """Test mood value at maximum is valid."""
        mood_data = MoodData(journal_id=1, mood_value=MAX_MOOD_VALUE)
        assert mood_data.mood_value == MAX_MOOD_VALUE

    def test_mood_value_below_min_raises_error(self):
        """Test that mood value below minimum raises error."""
        with pytest.raises(
            MoodDataValidationError,
            match=f"Mood value must be between {MIN_MOOD_VALUE} and {MAX_MOOD_VALUE}",
        ):
            MoodData(journal_id=1, mood_value=MIN_MOOD_VALUE - 1)

    def test_mood_value_above_max_raises_error(self):
        """Test that mood value above maximum raises error."""
        with pytest.raises(
            MoodDataValidationError,
            match=f"Mood value must be between {MIN_MOOD_VALUE} and {MAX_MOOD_VALUE}",
        ):
            MoodData(journal_id=1, mood_value=MAX_MOOD_VALUE + 1)


@pytest.mark.unit
class TestMoodDataEnergyLevelValidation:
    """Test MoodData energy_level validation."""

    def test_energy_level_at_min(self):
        """Test energy level at minimum is valid."""
        mood_data = MoodData(journal_id=1, energy_level=MIN_ENERGY_LEVEL)
        assert mood_data.energy_level == MIN_ENERGY_LEVEL

    def test_energy_level_at_max(self):
        """Test energy level at maximum is valid."""
        mood_data = MoodData(journal_id=1, energy_level=MAX_ENERGY_LEVEL)
        assert mood_data.energy_level == MAX_ENERGY_LEVEL

    def test_energy_level_below_min_raises_error(self):
        """Test that energy level below minimum raises error."""
        with pytest.raises(
            MoodDataValidationError,
            match=f"Energy level must be between {MIN_ENERGY_LEVEL} and {MAX_ENERGY_LEVEL}",
        ):
            MoodData(journal_id=1, energy_level=MIN_ENERGY_LEVEL - 1)

    def test_energy_level_above_max_raises_error(self):
        """Test that energy level above maximum raises error."""
        with pytest.raises(
            MoodDataValidationError,
            match=f"Energy level must be between {MIN_ENERGY_LEVEL} and {MAX_ENERGY_LEVEL}",
        ):
            MoodData(journal_id=1, energy_level=MAX_ENERGY_LEVEL + 1)


@pytest.mark.unit
class TestMoodDataMoodLabelValidation:
    """Test MoodData mood_label validation."""

    def test_mood_label_at_max_length(self):
        """Test mood label at max length is valid."""
        max_label = "a" * MAX_MOOD_LABEL_LENGTH
        mood_data = MoodData(journal_id=1, mood_label=max_label)
        assert len(mood_data.mood_label) == MAX_MOOD_LABEL_LENGTH  # type: ignore[arg-type]

    def test_mood_label_too_long_raises_error(self):
        """Test that mood label exceeding max length raises error."""
        long_label = "a" * (MAX_MOOD_LABEL_LENGTH + 1)
        with pytest.raises(
            MoodDataValidationError,
            match=f"Mood label cannot exceed {MAX_MOOD_LABEL_LENGTH}",
        ):
            MoodData(journal_id=1, mood_label=long_label)

