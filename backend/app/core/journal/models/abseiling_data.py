"""AbseilingData entity for the journal domain.

AbseilingData represents the ABSEILING_TRIP journal type data. A journal has the
ABSEILING_TRIP type if a row exists in the journal_abseiling_data table.

This entity stores abseiling-specific data including number of abseils and total length.
ABSEILING_TRIP requires the OUTDOOR_ACTIVITY and FITNESS types.

Note: Individual abseils are child journals with their own abseiling data. This
entity tracks the aggregate/trip-level data (total count, combined length).
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import AbseilingDataValidationError


@dataclass
class AbseilingData:
    """
    AbseilingData entity for ABSEILING_TRIP type journals.

    This entity represents additional data for journals that have the ABSEILING_TRIP
    type. A journal is considered to have the ABSEILING_TRIP type if a row exists in
    journal_abseiling_data for that journal_id.

    ABSEILING_TRIP automatically requires OUTDOOR_ACTIVITY and FITNESS types, which
    are resolved by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        number_of_abseils: Total number of individual abseil pitches (nullable, non-negative)
        total_length: Combined length of all abseils in metres (nullable, non-negative)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    number_of_abseils: int | None = None
    total_length: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate abseiling data properties."""
        self._validate_journal_id()
        self._validate_number_of_abseils()
        self._validate_total_length()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise AbseilingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_number_of_abseils(self) -> None:
        """Validate number_of_abseils is non-negative if provided."""
        if self.number_of_abseils is not None and self.number_of_abseils < 0:
            raise AbseilingDataValidationError(
                "number_of_abseils", "Number of abseils must be non-negative"
            )

    def _validate_total_length(self) -> None:
        """Validate total_length is non-negative if provided."""
        if self.total_length is not None and self.total_length < 0:
            raise AbseilingDataValidationError(
                "total_length", "Total length must be non-negative"
            )
