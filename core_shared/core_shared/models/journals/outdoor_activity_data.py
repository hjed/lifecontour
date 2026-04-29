"""OutdoorActivityData entity for the journal domain.

OutdoorActivityData represents the OUTDOOR_ACTIVITY journal type data. A journal
has the OUTDOOR_ACTIVITY type if a row exists in the journal_outdoor_activity_data
table.

This entity stores outdoor activity data including weather conditions, participant
role, and leadership information. The activity type is determined by which subtype
data tables exist (e.g. BUSHWALKING, ABSEILING_TRIP) rather than a free-text field.
OUTDOOR_ACTIVITY requires the FITNESS type (automatically added via type dependency
resolution).
"""

from dataclasses import dataclass
from datetime import datetime

from .constants import (
    MAX_PARTICIPANT_NOTES_LENGTH,
    MAX_ROLE_LENGTH,
    MAX_WEATHER_CONDITIONS_LENGTH,
)
from .exceptions import OutdoorActivityDataValidationError


@dataclass
class OutdoorActivityData:
    """
    OutdoorActivityData entity for OUTDOOR_ACTIVITY type journals.

    This entity represents additional data for journals that have the
    OUTDOOR_ACTIVITY type. A journal is considered to have the OUTDOOR_ACTIVITY
    type if a row exists in journal_outdoor_activity_data for that journal_id.

    OUTDOOR_ACTIVITY automatically requires the FITNESS type, which is resolved
    by the service layer's type dependency system.

    All fields except journal_id are optional.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        weather_conditions: Description of weather during activity (nullable)
        role: Participant's role in the activity (nullable)
        in_leadership_role: Whether the participant was in a leadership role (nullable)
        participant_notes: Notes about other participants (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    weather_conditions: str | None = None
    role: str | None = None
    in_leadership_role: bool | None = None
    participant_notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate outdoor activity data properties."""
        self._validate_journal_id()
        self._validate_weather_conditions()
        self._validate_role()
        self._validate_participant_notes()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise OutdoorActivityDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_weather_conditions(self) -> None:
        """Validate weather_conditions if provided."""
        if self.weather_conditions is not None:
            if not self.weather_conditions.strip():
                raise OutdoorActivityDataValidationError(
                    "weather_conditions",
                    "Weather conditions cannot be empty or whitespace",
                )
            if len(self.weather_conditions) > MAX_WEATHER_CONDITIONS_LENGTH:
                raise OutdoorActivityDataValidationError(
                    "weather_conditions",
                    f"Weather conditions cannot exceed {MAX_WEATHER_CONDITIONS_LENGTH} characters",
                )

    def _validate_role(self) -> None:
        """Validate role if provided."""
        if self.role is not None:
            if not self.role.strip():
                raise OutdoorActivityDataValidationError(
                    "role", "Role cannot be empty or whitespace"
                )
            if len(self.role) > MAX_ROLE_LENGTH:
                raise OutdoorActivityDataValidationError(
                    "role",
                    f"Role cannot exceed {MAX_ROLE_LENGTH} characters",
                )

    def _validate_participant_notes(self) -> None:
        """Validate participant_notes if provided."""
        if self.participant_notes is not None:
            if not self.participant_notes.strip():
                raise OutdoorActivityDataValidationError(
                    "participant_notes",
                    "Participant notes cannot be empty or whitespace",
                )
            if len(self.participant_notes) > MAX_PARTICIPANT_NOTES_LENGTH:
                raise OutdoorActivityDataValidationError(
                    "participant_notes",
                    f"Participant notes cannot exceed {MAX_PARTICIPANT_NOTES_LENGTH} characters",
                )
