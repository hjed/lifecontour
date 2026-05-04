"""OutdoorPlanningData entity for the journal domain.

OutdoorPlanningData represents the OUTDOOR_PLANNING journal type data.
This type extends EVENT rather than OUTDOOR_ACTIVITY and tracks topics
and related activity types.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .exceptions import OutdoorPlanningDataValidationError
from .outdoor_activity_subtypes import OutdoorActivitySubtype


@dataclass
class OutdoorPlanningData:
    """
    OutdoorPlanningData entity for OUTDOOR_PLANNING type journals.

    Attributes:
        journal_id: Foreign key to the journal
        topics: Free-text description of meeting topics
        activity_types: List of outdoor activity subtypes this meeting relates to
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    topics: str | None = None
    activity_types: list[str] | None = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate outdoor planning data properties."""
        self._validate_journal_id()
        self._validate_activity_types()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise OutdoorPlanningDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_activity_types(self) -> None:
        """Validate activity_types against allowed subtypes."""
        if self.activity_types:
            valid_subtypes = {subtype.value for subtype in OutdoorActivitySubtype}
            for activity_type in self.activity_types:
                if (
                    not isinstance(activity_type, str)
                    or activity_type not in valid_subtypes
                ):
                    raise OutdoorPlanningDataValidationError(
                        "activity_types",
                        f"Invalid activity type. Must be one of: {', '.join(sorted(valid_subtypes))}",
                    )
