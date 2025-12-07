"""MoodData entity for the journal domain.

MoodData represents the MOOD_RATING journal type data. A journal has the
MOOD_RATING type if a row exists in the journal_mood_data table.

This entity stores mood and energy tracking data for mood-type journals.
"""

from dataclasses import dataclass
from datetime import datetime

from .constants import (
    MAX_ENERGY_LEVEL,
    MAX_MOOD_LABEL_LENGTH,
    MAX_MOOD_VALUE,
    MIN_ENERGY_LEVEL,
    MIN_MOOD_VALUE,
)
from .exceptions import MoodDataValidationError


@dataclass
class MoodData:
    """
    MoodData entity for MOOD_RATING type journals.

    This entity represents additional data for journals that have the MOOD_RATING type.
    A journal is considered to have the MOOD_RATING type if a row exists in
    journal_mood_data for that journal_id.

    All fields except journal_id are optional, allowing users to track
    only mood, only energy, or both together.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        mood_value: Numeric mood rating (1-10 scale, nullable)
        mood_label: Text description of mood (e.g., "happy", "anxious")
        energy_level: Numeric energy rating (1-10 scale, nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    mood_value: int | None = None
    mood_label: str | None = None
    energy_level: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate mood data properties."""
        self._validate_journal_id()
        self._validate_mood_value()
        self._validate_mood_label()
        self._validate_energy_level()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise MoodDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_mood_value(self) -> None:
        """Validate mood_value is in 1-10 range if provided."""
        if self.mood_value is not None:
            if self.mood_value < MIN_MOOD_VALUE or self.mood_value > MAX_MOOD_VALUE:
                raise MoodDataValidationError(
                    "mood_value",
                    f"Mood value must be between {MIN_MOOD_VALUE} and {MAX_MOOD_VALUE}",
                )

    def _validate_mood_label(self) -> None:
        """Validate mood_label length if provided."""
        if self.mood_label is not None:
            if len(self.mood_label) > MAX_MOOD_LABEL_LENGTH:
                raise MoodDataValidationError(
                    "mood_label",
                    f"Mood label cannot exceed {MAX_MOOD_LABEL_LENGTH} characters",
                )

    def _validate_energy_level(self) -> None:
        """Validate energy_level is in 1-10 range if provided."""
        if self.energy_level is not None:
            if (
                self.energy_level < MIN_ENERGY_LEVEL
                or self.energy_level > MAX_ENERGY_LEVEL
            ):
                raise MoodDataValidationError(
                    "energy_level",
                    f"Energy level must be between {MIN_ENERGY_LEVEL} and {MAX_ENERGY_LEVEL}",
                )

    @property
    def has_mood_data(self) -> bool:
        """Check if any mood data is present."""
        return self.mood_value is not None or self.mood_label is not None

    @property
    def has_energy_data(self) -> bool:
        """Check if energy data is present."""
        return self.energy_level is not None
