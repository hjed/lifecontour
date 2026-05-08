"""OutdoorTrainingData entity for the journal domain.

OutdoorTrainingData represents the OUTDOOR_TRAINING journal type data.
This type extends OUTDOOR_ACTIVITY and FITNESS and tracks focus areas
related to outdoor activity subtypes, plus a free-text "other" option.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .exceptions import OutdoorTrainingDataValidationError


@dataclass
class OutdoorTrainingData:
    """
    OutdoorTrainingData entity for OUTDOOR_TRAINING type journals.

    Attributes:
        journal_id: Foreign key to the journal
        focus_areas: List of strings (activity subtypes or "other" free text)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    focus_areas: list[str] | None = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate outdoor training data properties."""
        self._validate_journal_id()
        self._validate_focus_areas()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise OutdoorTrainingDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_focus_areas(self) -> None:
        """Validate focus_areas are strings."""
        if self.focus_areas:
            # We allow strings. The UI allows selecting from OutdoorActivitySubtype
            # and entering a free-text "other" value. So we just ensure it's a list
            # of non-empty strings.
            for focus_area in self.focus_areas:
                if not isinstance(focus_area, str) or not focus_area.strip():
                    raise OutdoorTrainingDataValidationError(
                        "focus_areas",
                        "Focus areas must be non-empty strings",
                    )
