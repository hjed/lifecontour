"""CrossCountrySkiingData entity for the journal domain.

CrossCountrySkiingData represents the CROSS_COUNTRY_SKIING journal type data.
A journal has the CROSS_COUNTRY_SKIING type if a row exists in the
journal_skiing_data table.

This entity stores cross-country skiing specific data including route reference
and snow conditions.

CROSS_COUNTRY_SKIING requires BUSHWALKING, OUTDOOR_ACTIVITY, and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .exceptions import CrossCountrySkiingDataValidationError


@dataclass
class CrossCountrySkiingData:
    """
    CrossCountrySkiingData entity for CROSS_COUNTRY_SKIING type journals.

    This entity represents additional data for journals that have the
    CROSS_COUNTRY_SKIING type. A journal is considered to have the
    CROSS_COUNTRY_SKIING type if a row exists in journal_skiing_data
    for that journal_id.

    CROSS_COUNTRY_SKIING automatically requires BUSHWALKING, OUTDOOR_ACTIVITY,
    and FITNESS types, which are resolved by the service layer's type dependency
    system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        route_id: UUID reference to a route (from the routes domain) (nullable)
        snow_conditions: Description of snow conditions (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    route_id: UUID | None = None
    snow_conditions: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate cross-country skiing data properties."""
        self._validate_journal_id()
        self._validate_snow_conditions()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise CrossCountrySkiingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_snow_conditions(self) -> None:
        """Validate snow_conditions is non-empty if provided."""
        if self.snow_conditions is not None and self.snow_conditions == "":
            raise CrossCountrySkiingDataValidationError(
                "snow_conditions", "Snow conditions must not be an empty string"
            )
