"""ClimbingData entity for the journal domain.

ClimbingData represents the CLIMBING journal type data. A journal has the CLIMBING
type if a row exists in the journal_climbing_data table.

This entity stores climbing-specific data including route reference, climbing type,
grade, and route length.

CLIMBING requires OUTDOOR_ACTIVITY and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime

from .constants import VALID_CLIMBING_TYPES
from .exceptions import ClimbingDataValidationError


@dataclass
class ClimbingData:
    """
    ClimbingData entity for CLIMBING type journals.

    This entity represents additional data for journals that have the CLIMBING
    type. A journal is considered to have the CLIMBING type if a row exists in
    journal_climbing_data for that journal_id.

    CLIMBING automatically requires OUTDOOR_ACTIVITY and FITNESS types, which
    are resolved by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        climbing_type: Type of climbing (sport, trad, bouldering) (nullable)
        grade: Numeric climbing grade (nullable, non-negative)
        length: Route length in metres (nullable, non-negative)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    climbing_type: str | None = None
    grade: int | None = None
    length: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate climbing data properties."""
        self._validate_journal_id()
        self._validate_climbing_type()
        self._validate_grade()
        self._validate_length()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise ClimbingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_climbing_type(self) -> None:
        """Validate climbing_type is one of the valid values if provided."""
        if self.climbing_type is None:
            return
        if self.climbing_type not in VALID_CLIMBING_TYPES:
            raise ClimbingDataValidationError(
                "climbing_type",
                f"Invalid climbing type '{self.climbing_type}'. "
                f"Valid values: {', '.join(VALID_CLIMBING_TYPES)}",
            )

    def _validate_grade(self) -> None:
        """Validate grade is non-negative if provided."""
        if self.grade is not None and self.grade < 0:
            raise ClimbingDataValidationError("grade", "Grade must be non-negative")

    def _validate_length(self) -> None:
        """Validate length is non-negative if provided."""
        if self.length is not None and self.length < 0:
            raise ClimbingDataValidationError("length", "Length must be non-negative")
