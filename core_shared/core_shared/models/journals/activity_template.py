"""ActivityTemplate entity for the journal domain.

ActivityTemplate represents a reusable canyon, cave, or climb definition.
Templates are user-owned entities that pre-populate pitch data when selected
during journal creation.

Templates are separate from Routes (which track GPS data). They define
pitch characteristics and type-specific metadata.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .constants import (
    MAX_REGION_LENGTH,
    MAX_TEMPLATE_NAME_LENGTH,
    MAX_WATER_GAUGE_NAME_LENGTH,
    VALID_CANYON_TYPES,
    VALID_CLIMBING_TYPES,
    VALID_TEMPLATE_TYPES,
)
from .exceptions import ActivityTemplateValidationError
from .template_pitch import TemplatePitch


@dataclass
class ActivityTemplate:
    """
    ActivityTemplate entity for reusable canyon/cave/climb definitions.

    Templates are user-owned and searchable by name. When selected during
    journal creation, their standard pitches are copied into the journal's
    abseil pitch data as editable defaults.

    Attributes:
        name: Searchable template name (required, max 200 chars)
        template_type: Type of template — canyoning, caving, or climbing (required)
        user_id: Owner user ID (required)
        id: UUID primary key (auto-generated if not provided)
        region: Geographic region (nullable)
        description: Free-text description (nullable)
        pitches: List of standard template pitches (defaults to empty list)
        french_grade: French canyon grading (canyoning-specific, nullable)
        canyon_type: Canyon type — vertical, aquatic, mixed (canyoning-specific, nullable)
        water_gauge_name: Water gauge name (canyoning-specific, nullable)
        is_vertical: Whether the cave is primarily vertical (caving-specific, nullable)
        is_horizontal: Whether the cave is primarily horizontal (caving-specific, nullable)
        climbing_type: Climbing type — sport, trad, bouldering (climbing-specific, nullable)
        grade: Climbing grade (climbing-specific, nullable)
        length: Route length in metres (climbing-specific, nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    name: str
    template_type: str
    user_id: str
    id: str | None = None
    region: str | None = None
    description: str | None = None
    pitches: list[TemplatePitch] = field(default_factory=list)
    # Canyoning-specific fields
    french_grade: str | None = None
    canyon_type: str | None = None
    water_gauge_name: str | None = None
    # Caving-specific fields
    is_vertical: bool | None = None
    is_horizontal: bool | None = None
    # Climbing-specific fields
    climbing_type: str | None = None
    grade: int | None = None
    length: int | None = None
    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate and set defaults for activity template properties."""
        if self.id is None:
            self.id = str(uuid.uuid4())
        self._validate_name()
        self._validate_template_type()
        self._enforce_type_exclusivity()
        self._validate_user_id()
        self._validate_region()
        self._validate_canyon_type()
        self._validate_water_gauge_name()
        self._validate_climbing_type()
        self._reconcile_pitches()

    def _reconcile_pitches(self) -> None:
        """Ensure all pitches are assigned this template's ID."""
        if self.id is not None:
            for pitch in self.pitches:
                pitch.template_id = self.id

    def _validate_region(self) -> None:
        """Validate region length if provided."""
        if self.region is not None and len(self.region) > MAX_REGION_LENGTH:
            raise ActivityTemplateValidationError(
                "region",
                f"Region must not exceed {MAX_REGION_LENGTH} characters",
            )

    def _validate_water_gauge_name(self) -> None:
        """Validate water gauge name length if provided."""
        if (
            self.water_gauge_name is not None
            and len(self.water_gauge_name) > MAX_WATER_GAUGE_NAME_LENGTH
        ):
            raise ActivityTemplateValidationError(
                "water_gauge_name",
                f"Water gauge name must not exceed {MAX_WATER_GAUGE_NAME_LENGTH} characters",
            )

    def _enforce_type_exclusivity(self) -> None:
        """Ensure type-specific fields are only set for their corresponding template type."""
        if self.template_type != "canyoning":
            self.french_grade = None
            self.canyon_type = None
            self.water_gauge_name = None
        if self.template_type != "caving":
            self.is_vertical = None
            self.is_horizontal = None
        if self.template_type != "climbing":
            self.climbing_type = None
            self.grade = None
            self.length = None

    def _validate_name(self) -> None:
        """Validate name is non-empty and within length limit."""
        if not self.name or not self.name.strip():
            raise ActivityTemplateValidationError(
                "name", "Template name must be a non-empty string"
            )
        if len(self.name) > MAX_TEMPLATE_NAME_LENGTH:
            raise ActivityTemplateValidationError(
                "name",
                f"Template name must not exceed {MAX_TEMPLATE_NAME_LENGTH} characters",
            )

    def _validate_template_type(self) -> None:
        """Validate template_type is one of the valid values."""
        if not self.template_type or self.template_type not in VALID_TEMPLATE_TYPES:
            raise ActivityTemplateValidationError(
                "template_type",
                f"Template type must be one of: {', '.join(VALID_TEMPLATE_TYPES)}",
            )

    def _validate_user_id(self) -> None:
        """Validate user_id is non-empty."""
        if not self.user_id or not self.user_id.strip():
            raise ActivityTemplateValidationError(
                "user_id", "User ID must be a non-empty string"
            )

    def _validate_canyon_type(self) -> None:
        """Validate canyon_type is one of the valid values if provided."""
        if self.canyon_type is not None:
            if self.canyon_type not in VALID_CANYON_TYPES:
                raise ActivityTemplateValidationError(
                    "canyon_type",
                    f"Canyon type must be one of: {', '.join(VALID_CANYON_TYPES)}",
                )

    def _validate_climbing_type(self) -> None:
        """Validate climbing_type is one of the valid values if provided."""
        if self.climbing_type is not None:
            if self.climbing_type not in VALID_CLIMBING_TYPES:
                raise ActivityTemplateValidationError(
                    "climbing_type",
                    f"Climbing type must be one of: {', '.join(VALID_CLIMBING_TYPES)}",
                )
