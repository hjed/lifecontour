"""KayakingData entity for the journal domain.

KayakingData represents the KAYAKING journal type data. A journal has the KAYAKING
type if a row exists in the journal_kayaking_data table.

This entity stores kayaking-specific data including route reference and water type.

KAYAKING requires OUTDOOR_ACTIVITY and FITNESS types.
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import KayakingDataValidationError


@dataclass
class KayakingData:
    """
    KayakingData entity for KAYAKING type journals.

    This entity represents additional data for journals that have the KAYAKING
    type. A journal is considered to have the KAYAKING type if a row exists in
    journal_kayaking_data for that journal_id.

    KAYAKING automatically requires OUTDOOR_ACTIVITY and FITNESS types, which
    are resolved by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        water_type: Type of water (e.g., river, sea, lake) (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    water_type: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate kayaking data properties."""
        self._validate_journal_id()
        self._validate_water_type()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise KayakingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_water_type(self) -> None:
        """Validate water_type is non-empty if provided."""
        if self.water_type is not None and self.water_type == "":
            raise KayakingDataValidationError(
                "water_type", "Water type must not be an empty string"
            )
