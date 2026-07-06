"""CavingData entity for the journal domain.

CavingData represents the CAVING journal type data. A journal has the CAVING
type if a row exists in the journal_caving_data table.

This entity stores caving-specific data including template reference, and boolean
flags for cave characteristics (vertical, horizontal).

CAVING requires ABSEILING_TRIP, OUTDOOR_ACTIVITY, and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import CavingDataValidationError


@dataclass
class CavingData:
    """
    CavingData entity for CAVING type journals.

    This entity represents additional data for journals that have the CAVING
    type. A journal is considered to have the CAVING type if a row exists in
    journal_caving_data for that journal_id.

    CAVING automatically requires ABSEILING_TRIP, OUTDOOR_ACTIVITY,
    and FITNESS types, which are resolved by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        is_vertical: Whether the cave is primarily vertical (nullable)
        is_horizontal: Whether the cave is primarily horizontal (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    is_vertical: bool | None = None
    is_horizontal: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate caving data properties."""
        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise CavingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )
