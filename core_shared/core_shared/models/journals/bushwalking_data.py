"""BushwalkingData entity for the journal domain.

BushwalkingData represents the BUSHWALKING journal type data. A journal has the
BUSHWALKING type if a row exists in the journal_bushwalking_data table.

This entity stores bushwalking-specific data including route reference and
Australian Track Grading System classification. BUSHWALKING requires both
OUTDOOR_ACTIVITY and FITNESS types (automatically added via type dependency
resolution).

Australian Track Grading System:
    Grade 1: Well-formed track, suitable for wheelchairs
    Grade 2: Well-formed track, suitable for most ages and fitness levels
    Grade 3: Formed track, some steep sections, may require navigation skills
    Grade 4: Rough track, very steep sections, requires good fitness and skills
    Grade 5: Route only, very rough, very steep, requires specialised skills
"""

from dataclasses import dataclass
from datetime import datetime

from .constants import VALID_TRACK_GRADES
from .exceptions import BushwalkingDataValidationError


@dataclass
class BushwalkingData:
    """
    BushwalkingData entity for BUSHWALKING type journals.

    This entity represents additional data for journals that have the BUSHWALKING
    type. A journal is considered to have the BUSHWALKING type if a row exists in
    journal_bushwalking_data for that journal_id.

    BUSHWALKING automatically requires OUTDOOR_ACTIVITY and FITNESS types, which
    are resolved by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        track_grading: Australian Track Grading System grade (Grade 1-5) (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    track_grading: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate bushwalking data properties."""
        self._validate_journal_id()
        self._validate_track_grading()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise BushwalkingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_track_grading(self) -> None:
        """Validate track_grading is a valid Australian Track Grade if provided."""
        if self.track_grading is not None:
            if self.track_grading not in VALID_TRACK_GRADES:
                raise BushwalkingDataValidationError(
                    "track_grading",
                    f"Track grading must be one of: {', '.join(VALID_TRACK_GRADES)}",
                )
