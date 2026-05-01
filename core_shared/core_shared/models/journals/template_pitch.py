"""TemplatePitch entity for the journal domain.

TemplatePitch represents a standard abseil pitch within an ActivityTemplate.
Pitches are stored in the template_pitches table with a foreign key to
activity_templates.

Each pitch records height, anchor location/type, and whether the user
typically performs a rescue or sets up the abseil. These fields share
the same constraints as AbseilPitch.
"""

from dataclasses import dataclass
from datetime import datetime

from .constants import VALID_ANCHOR_LOCATIONS, VALID_ANCHOR_TYPES
from .exceptions import TemplatePitchValidationError


@dataclass
class TemplatePitch:
    """
    TemplatePitch entity for standard pitches within a template.

    Template pitches define the default pitch data for a canyon, cave, or
    climb. When a template is selected during journal creation, these
    pitches are copied into the journal's abseil pitch data as editable
    defaults.

    Attributes:
        template_id: Foreign key to activity_templates (required, UUID string)
        pitch_number: Sequential pitch number within the template (required, positive)
        id: Auto-generated primary key (nullable for new entities)
        height: Height of the pitch in metres (nullable, non-negative)
        anchor_location: Where the anchor is positioned — TR, TL, or Centre (nullable)
        anchor_type: Type of anchor used (nullable, constrained to valid values)
        did_rescue: Whether a rescue is typically performed on this pitch (nullable)
        did_setup: Whether the user typically sets up the abseil on this pitch (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    template_id: str
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
        """Validate template pitch properties."""
        self._validate_template_id()
        self._validate_pitch_number()
        self._validate_height()
        self._validate_anchor_location()
        self._validate_anchor_type()

    def _validate_template_id(self) -> None:
        """Validate template_id is non-empty."""
        if not self.template_id:
            raise TemplatePitchValidationError(
                "template_id", "Template ID must be a non-empty string"
            )

    def _validate_pitch_number(self) -> None:
        """Validate pitch_number is positive."""
        if self.pitch_number <= 0:
            raise TemplatePitchValidationError(
                "pitch_number", "Pitch number must be a positive integer"
            )

    def _validate_height(self) -> None:
        """Validate height is non-negative if provided."""
        if self.height is not None and self.height < 0:
            raise TemplatePitchValidationError("height", "Height must be non-negative")

    def _validate_anchor_location(self) -> None:
        """Validate anchor_location is one of the valid values if provided."""
        if self.anchor_location is not None:
            if self.anchor_location not in VALID_ANCHOR_LOCATIONS:
                raise TemplatePitchValidationError(
                    "anchor_location",
                    f"Anchor location must be one of: {', '.join(VALID_ANCHOR_LOCATIONS)}",
                )

    def _validate_anchor_type(self) -> None:
        """Validate anchor_type is one of the valid values if provided."""
        if self.anchor_type is not None:
            if self.anchor_type not in VALID_ANCHOR_TYPES:
                raise TemplatePitchValidationError(
                    "anchor_type",
                    f"Anchor type must be one of: {', '.join(VALID_ANCHOR_TYPES)}",
                )
