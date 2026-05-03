"""DivingData entity for the journal domain.

DivingData represents the DIVING journal type data. A journal has the DIVING
type if a row exists in the journal_diving_data table.

DIVING requires OUTDOOR_ACTIVITY and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import DivingDataValidationError


@dataclass
class DivingData:
    """
    DivingData entity for DIVING type journals.

    This entity represents additional data for journals that have the DIVING
    type. A journal is considered to have the DIVING type if a row exists in
    journal_diving_data for that journal_id.

    DIVING automatically requires OUTDOOR_ACTIVITY and FITNESS types,
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
        """Validate diving data properties."""
        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise DivingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )
