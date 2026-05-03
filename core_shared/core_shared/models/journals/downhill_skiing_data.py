"""DownhillSkiingData entity for the journal domain.

DownhillSkiingData represents the DOWNHILL_SKIING journal type data. A journal has the DOWNHILL_SKIING
type if a row exists in the journal_downhill_skiing_data table.

DOWNHILL_SKIING requires OUTDOOR_ACTIVITY and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import DownhillSkiingDataValidationError


@dataclass
class DownhillSkiingData:
    """
    DownhillSkiingData entity for DOWNHILL_SKIING type journals.

    This entity represents additional data for journals that have the DOWNHILL_SKIING
    type. A journal is considered to have the DOWNHILL_SKIING type if a row exists in
    journal_downhill_skiing_data for that journal_id.

    DOWNHILL_SKIING automatically requires OUTDOOR_ACTIVITY and FITNESS types,
    which are resolved by the service layer's type dependency system.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate downhill skiing data properties."""
        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise DownhillSkiingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )
