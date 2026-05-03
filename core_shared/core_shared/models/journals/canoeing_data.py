"""CanoeingData entity for the journal domain.

CanoeingData represents the CANOEING journal type data. A journal has the CANOEING
type if a row exists in the journal_canoeing_data table.

This entity stores canoeing-specific data including the water type
(river, lake, sea).

CANOEING requires OUTDOOR_ACTIVITY and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import CanoeingDataValidationError


@dataclass
class CanoeingData:
    """
    CanoeingData entity for CANOEING type journals.

    This entity represents additional data for journals that have the CANOEING
    type. A journal is considered to have the CANOEING type if a row exists in
    journal_canoeing_data for that journal_id.

    CANOEING automatically requires OUTDOOR_ACTIVITY and FITNESS types,
    which are resolved by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        water_type: Type of water body (river, lake, sea) (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    water_type: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate canoeing data properties."""
        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise CanoeingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )
