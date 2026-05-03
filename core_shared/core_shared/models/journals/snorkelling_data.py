"""SnorkellingData entity for the journal domain.

SnorkellingData represents the SNORKELLING journal type data. A journal has the SNORKELLING
type if a row exists in the journal_snorkelling_data table.

SNORKELLING requires OUTDOOR_ACTIVITY and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import SnorkellingDataValidationError


@dataclass
class SnorkellingData:
    """
    SnorkellingData entity for SNORKELLING type journals.

    This entity represents additional data for journals that have the SNORKELLING
    type. A journal is considered to have the SNORKELLING type if a row exists in
    journal_snorkelling_data for that journal_id.

    SNORKELLING automatically requires OUTDOOR_ACTIVITY and FITNESS types,
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
        """Validate snorkelling data properties."""
        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise SnorkellingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )
