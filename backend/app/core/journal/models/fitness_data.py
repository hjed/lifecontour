"""FitnessData entity for the journal domain.

FitnessData represents the FITNESS journal type data. A journal has the
FITNESS type if a row exists in the journal_fitness_data table.

This entity stores fitness activity data including heart rate, distance,
elevation, duration, calories, GPX tracks, and Strava integration.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from .constants import MAX_STRAVA_ACTIVITY_ID_LENGTH
from .exceptions import FitnessDataValidationError


@dataclass
class FitnessData:
    """
    FitnessData entity for FITNESS type journals.

    This entity represents additional data for journals that have the FITNESS type.
    A journal is considered to have the FITNESS type if a row exists in
    journal_fitness_data for that journal_id.

    All fields except journal_id are optional, allowing users to track
    different metrics based on the activity type.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        heart_rate_avg: Average heart rate in BPM (nullable)
        heart_rate_max: Maximum heart rate in BPM (nullable)
        distance: Distance in meters (nullable)
        elevation_gain: Elevation gain in meters (nullable)
        elevation_loss: Elevation loss in meters (nullable)
        duration: Duration in seconds (nullable)
        calories: Calories burned (nullable)
        gpx_track_data: GPX track data as XML text (nullable)
        strava_activity_id: Strava activity ID for integration (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    heart_rate_avg: int | None = None
    heart_rate_max: int | None = None
    distance: int | None = None
    elevation_gain: int | None = None
    elevation_loss: int | None = None
    duration: int | None = None
    calories: int | None = None
    gpx_track_data: str | None = None
    strava_activity_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate fitness data properties."""
        self._validate_journal_id()
        self._validate_heart_rate_avg()
        self._validate_heart_rate_max()
        self._validate_distance()
        self._validate_elevation_gain()
        self._validate_elevation_loss()
        self._validate_duration()
        self._validate_calories()
        self._validate_gpx_track_data()
        self._validate_strava_activity_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise FitnessDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_heart_rate_avg(self) -> None:
        """Validate heart_rate_avg is positive if provided."""
        if self.heart_rate_avg is not None and self.heart_rate_avg < 0:
            raise FitnessDataValidationError(
                "heart_rate_avg", "Heart rate average must be positive"
            )

    def _validate_heart_rate_max(self) -> None:
        """Validate heart_rate_max is positive if provided."""
        if self.heart_rate_max is not None and self.heart_rate_max < 0:
            raise FitnessDataValidationError(
                "heart_rate_max", "Heart rate max must be positive"
            )

    def _validate_distance(self) -> None:
        """Validate distance is positive if provided."""
        if self.distance is not None and self.distance < 0:
            raise FitnessDataValidationError("distance", "Distance must be positive")

    def _validate_elevation_gain(self) -> None:
        """Validate elevation_gain is positive if provided."""
        if self.elevation_gain is not None and self.elevation_gain < 0:
            raise FitnessDataValidationError(
                "elevation_gain", "Elevation gain must be positive"
            )

    def _validate_elevation_loss(self) -> None:
        """Validate elevation_loss is positive if provided."""
        if self.elevation_loss is not None and self.elevation_loss < 0:
            raise FitnessDataValidationError(
                "elevation_loss", "Elevation loss must be positive"
            )

    def _validate_duration(self) -> None:
        """Validate duration is positive if provided."""
        if self.duration is not None and self.duration < 0:
            raise FitnessDataValidationError("duration", "Duration must be positive")

    def _validate_calories(self) -> None:
        """Validate calories is positive if provided."""
        if self.calories is not None and self.calories < 0:
            raise FitnessDataValidationError("calories", "Calories must be positive")

    def _validate_gpx_track_data(self) -> None:
        """Validate GPX track data is valid XML with <gpx> root element if provided."""
        if self.gpx_track_data is not None:
            if not self.gpx_track_data.strip():
                raise FitnessDataValidationError(
                    "gpx_track_data", "GPX data cannot be empty"
                )

            # Validate XML format
            try:
                root = ET.fromstring(self.gpx_track_data)
            except ET.ParseError as e:
                raise FitnessDataValidationError(
                    "gpx_track_data", "GPX data must be valid XML"
                ) from e

            # Validate <gpx> root element
            # Remove namespace if present for comparison
            tag_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag
            if tag_name != "gpx":
                raise FitnessDataValidationError(
                    "gpx_track_data", "GPX data must have <gpx> root element"
                )

    def _validate_strava_activity_id(self) -> None:
        """Validate Strava activity ID if provided."""
        if self.strava_activity_id is not None:
            if not self.strava_activity_id.strip():
                raise FitnessDataValidationError(
                    "strava_activity_id", "Strava activity ID cannot be empty"
                )
            if len(self.strava_activity_id) > MAX_STRAVA_ACTIVITY_ID_LENGTH:
                raise FitnessDataValidationError(
                    "strava_activity_id",
                    f"Strava activity ID cannot exceed {MAX_STRAVA_ACTIVITY_ID_LENGTH} characters",
                )
