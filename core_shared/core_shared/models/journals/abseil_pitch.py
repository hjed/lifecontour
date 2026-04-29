"""AbseilPitch entity for the journal domain.

AbseilPitch represents an individual abseil pitch within an ABSEILING_TRIP journal.
Pitches are stored in the abseil_pitches table with a foreign key to
journal_abseiling_data.

Each pitch records height, anchor location/type, and whether the user
performed a rescue or set up the abseil.
"""

from dataclasses import dataclass
from datetime import datetime

from .constants import VALID_ANCHOR_LOCATIONS, VALID_ANCHOR_TYPES
from .exceptions import AbseilPitchValidationError


@dataclass
class AbseilPitch:
    """
    AbseilPitch entity for individual abseil pitches.

    Pitches belong to a journal that has the ABSEILING_TRIP type. Multiple
    pitches can exist per journal, ordered by pitch_number.

    Attributes:
        journal_id: Foreign key to journal_abseiling_data (required)
        pitch_number: Sequential pitch number within the journal (required, positive)
        id: Auto-generated primary key (nullable for new entities)
        height: Height of the pitch in metres (nullable, non-negative)
        anchor_location: Where the anchor is positioned — TR, TL, or Centre (nullable)
        anchor_type: Type of anchor used (nullable, constrained to valid values)
        did_rescue: Whether a rescue was performed on this pitch (nullable)
        did_setup: Whether the user set up the abseil on this pitch (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    pitch_number: int
    id: int | None = None
    height: int | None = None
    anchor_location: str | None = None
    anchor_type: str | None = None
    did_rescue: bool | None = None
    did_setup: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate abseil pitch properties."""
        self._validate_journal_id()
        self._validate_pitch_number()
        self._validate_height()
        self._validate_anchor_location()
        self._validate_anchor_type()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise AbseilPitchValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_pitch_number(self) -> None:
        """Validate pitch_number is positive."""
        if self.pitch_number <= 0:
            raise AbseilPitchValidationError(
                "pitch_number", "Pitch number must be a positive integer"
            )

    def _validate_height(self) -> None:
        """Validate height is non-negative if provided."""
        if self.height is not None and self.height < 0:
            raise AbseilPitchValidationError("height", "Height must be non-negative")

    def _validate_anchor_location(self) -> None:
        """Validate anchor_location is one of the valid values if provided."""
        if self.anchor_location is not None:
            if self.anchor_location not in VALID_ANCHOR_LOCATIONS:
                raise AbseilPitchValidationError(
                    "anchor_location",
                    f"Anchor location must be one of: {', '.join(VALID_ANCHOR_LOCATIONS)}",
                )

    def _validate_anchor_type(self) -> None:
        """Validate anchor_type is one of the valid values if provided."""
        if self.anchor_type is not None:
            if self.anchor_type not in VALID_ANCHOR_TYPES:
                raise AbseilPitchValidationError(
                    "anchor_type",
                    f"Anchor type must be one of: {', '.join(VALID_ANCHOR_TYPES)}",
                )
