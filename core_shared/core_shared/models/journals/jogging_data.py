"""JoggingData entity for the journal domain.

JoggingData represents the JOGGING journal type data. A journal has the JOGGING
type if a row exists in the journal_jogging_data table.

This entity stores jogging-specific data including route reference and pace.
JOGGING requires the FITNESS type only (NOT OUTDOOR_ACTIVITY - this is critical
as jogging may occur on treadmills or indoor tracks).
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import JoggingDataValidationError


@dataclass
class JoggingData:
    """
    JoggingData entity for JOGGING type journals.

    This entity represents additional data for journals that have the JOGGING
    type. A journal is considered to have the JOGGING type if a row exists in
    journal_jogging_data for that journal_id.

    JOGGING automatically requires the FITNESS type only (not OUTDOOR_ACTIVITY,
    since jogging can take place indoors), which is resolved by the service
    layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        pace: Pace in seconds per kilometre (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    pace: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate jogging data properties."""
        self._validate_journal_id()
        self._validate_pace()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise JoggingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_pace(self) -> None:
        """Validate pace is non-negative if provided."""
        if self.pace is not None and self.pace < 0:
            raise JoggingDataValidationError("pace", "Pace must be non-negative")
