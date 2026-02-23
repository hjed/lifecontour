"""CanyoningData entity for the journal domain.

CanyoningData represents the CANYONING journal type data. A journal has the CANYONING
type if a row exists in the journal_canyoning_data table.

This entity stores canyoning-specific data including route reference, French grade,
water gauge data, and boolean flags for canyon characteristics.

CANYONING requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, and FITNESS types.

French Canyon Grading System:
  Format: v[vertical]a[aquatic][engagement][stars]
  Example: v3a2IV** = vertical grade 3, aquatic grade 2, engagement IV, 2 stars
  - Vertical: 1-7 (difficulty of abseils)
  - Aquatic: 1-7 (difficulty of water sections)
  - Engagement: I-VI (commitment level, optional)
  - Stars: * to *** (quality/beauty, optional)
"""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .constants import FRENCH_CANYON_GRADE_PATTERN
from .exceptions import CanyoningDataValidationError


@dataclass
class CanyoningData:
    """
    CanyoningData entity for CANYONING type journals.

    This entity represents additional data for journals that have the CANYONING
    type. A journal is considered to have the CANYONING type if a row exists in
    journal_canyoning_data for that journal_id.

    CANYONING automatically requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY,
    and FITNESS types, which are resolved by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        route_id: UUID reference to a route (from the routes domain) (nullable)
        french_grade: French canyon grade string e.g. "v3a2IV**" (nullable)
        water_guage_name: Name of the water gauge used for flow measurement (nullable)
        water_guage_level: Water gauge reading at time of trip (nullable)
        is_vertical: Whether the canyon is primarily vertical (nullable)
        is_night_canyon: Whether the trip was done at night (nullable)
        is_white_water: Whether the canyon has significant white water (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    route_id: UUID | None = None
    french_grade: str | None = None
    water_guage_name: str | None = None
    water_guage_level: int | None = None
    is_vertical: bool | None = None
    is_night_canyon: bool | None = None
    is_white_water: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate canyoning data properties."""
        self._validate_journal_id()
        self._validate_french_grade()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise CanyoningDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_french_grade(self) -> None:
        """Validate french_grade matches the French canyon grading format if provided.

        Valid format: v[1-7]a[1-7][I-VI optional][* to *** optional]
        Examples: v3a2, v3a2IV, v3a2**, v3a2IV**
        """
        if self.french_grade is None:
            return
        if not re.match(FRENCH_CANYON_GRADE_PATTERN, self.french_grade):
            raise CanyoningDataValidationError(
                "french_grade",
                f"Invalid French canyon grade '{self.french_grade}'. "
                "Expected format: v[1-7]a[1-7][I-VI][*-***] "
                "(e.g. 'v3a2IV**')",
            )
