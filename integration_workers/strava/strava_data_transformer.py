"""
Strava activity data transformer.

Converts Strava API activity responses into journal domain data:
- Activity type mapping: Strava type → journal type hierarchy
- Field transformation: Strava fields → journal fields
- GPX generation from stream data
- Elevation loss calculation from altitude stream

This is pure transformation logic with no I/O or database access.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core_shared.models.journals import EventDateRange, JournalType

from elevation_calculator import calculate_elevation_loss
from gpx_generator import generate_gpx
from strava_models import StravaActivity, StravaStreamSet

# ------------------------------------------------------------------ #
# Activity type mapping table                                        #
# Strava type → list of JournalType values per product specification #
# ------------------------------------------------------------------ #

_STRAVA_TYPE_MAP: dict[str, list[JournalType]] = {
    "Run": [JournalType.JOGGING, JournalType.FITNESS],
    "TrailRun": [
        JournalType.JOGGING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "Hike": [
        JournalType.BUSHWALKING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "Walk": [
        JournalType.BUSHWALKING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "Ride": [JournalType.FITNESS],
    "MountainBikeRide": [JournalType.OUTDOOR_ACTIVITY, JournalType.FITNESS],
    "Swim": [JournalType.FITNESS],
    "Kayaking": [
        JournalType.KAYAKING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "Canoeing": [
        JournalType.CANOEING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "RockClimbing": [
        JournalType.CLIMBING,
        JournalType.ABSEILING_TRIP,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "NordicSki": [
        JournalType.CROSS_COUNTRY_SKIING,
        JournalType.BUSHWALKING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "BackcountrySki": [
        JournalType.CROSS_COUNTRY_SKIING,
        JournalType.BUSHWALKING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "AlpineSki": [
        JournalType.DOWNHILL_SKIING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "Snowshoe": [
        JournalType.BUSHWALKING,
        JournalType.OUTDOOR_ACTIVITY,
        JournalType.FITNESS,
    ],
    "Rowing": [JournalType.FITNESS],
    "Surfing": [JournalType.FITNESS],
    "Yoga": [JournalType.FITNESS],
    "Other": [JournalType.FITNESS],
}

# Default for unmapped Strava types
_DEFAULT_JOURNAL_TYPES: list[JournalType] = [JournalType.FITNESS]


@dataclass(frozen=True)
class TransformedActivity:
    """Result of transforming a Strava activity into journal domain data.

    This is a pure data object holding all fields needed to create a
    journal from a Strava activity. ``journal_id`` is not included
    because it is assigned during journal creation in Phase 2.

    Attributes:
        title: Journal title (from Strava activity name).
        content: Journal content (from Strava activity description).
        event_date_range: Start/end time range of the activity.
        journal_types: List of journal types to assign.
        fitness_data_distance: Distance in metres (rounded int).
        fitness_data_elevation_gain: Elevation gain in metres (rounded int).
        fitness_data_duration: Moving time in seconds.
        fitness_data_calories: Calories burned (rounded int, nullable).
        fitness_data_heart_rate_avg: Average heart rate (rounded int, nullable).
        fitness_data_heart_rate_max: Max heart rate (rounded int, nullable).
        fitness_data_strava_activity_id: Strava activity ID as string.
        elevation_loss: Elevation loss in metres (derived from altitude stream, nullable).
        gpx_xml: Generated GPX XML string (nullable).
        climbing_indoor: Whether a climbing activity is indoor. Strava has no
            distinct indoor-climbing sport type, so this is inferred from the
            absence of GPS coordinates (indoor activities have no GPS). Always
            False for non-climbing activities.
    """

    title: str
    content: str | None
    event_date_range: EventDateRange
    journal_types: list[JournalType]
    fitness_data_distance: int
    fitness_data_elevation_gain: int
    fitness_data_duration: int
    fitness_data_calories: int | None
    fitness_data_heart_rate_avg: int | None
    fitness_data_heart_rate_max: int | None
    fitness_data_strava_activity_id: str
    elevation_loss: int | None
    gpx_xml: str | None
    version_hash: str
    strava_athletes: list[dict[str, Any]]
    climbing_indoor: bool = False


class StravaDataTransformer:
    """Transforms Strava API activity data into journal domain objects.

    All methods are stateless and can be called as classmethods.
    No I/O or database access is performed.
    """

    @staticmethod
    def map_activity_types(strava_type: str) -> list[JournalType]:
        """Map a Strava activity type to journal type hierarchy.

        Args:
            strava_type: Strava activity type string (e.g. ``"Run"``,
                ``"Hike"``, ``"Kayaking"``).

        Returns:
            List of ``JournalType`` values. Unmapped types default
            to ``[FITNESS]``.
        """
        return list(_STRAVA_TYPE_MAP.get(strava_type, _DEFAULT_JOURNAL_TYPES))

    @staticmethod
    def transform(
        activity: StravaActivity,
        *,
        streams: StravaStreamSet | None = None,
    ) -> TransformedActivity:
        """Transform a Strava activity into journal domain data.

        Args:
            activity: Strava API activity response.
            streams: Optional stream data (latlng, altitude, time) for
                GPX generation and elevation loss calculation.

        Returns:
            ``TransformedActivity`` with all journal fields populated.
        """
        # Parse start time
        start_dt = datetime.fromisoformat(activity.start_date.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(seconds=activity.elapsed_time)

        # Type mapping
        journal_types = StravaDataTransformer.map_activity_types(activity.type)

        # Indoor climbing detection: Strava has no distinct indoor-climbing sport
        # type, so a climbing activity with no GPS coordinates is treated as indoor.
        climbing_indoor = (
            JournalType.CLIMBING in journal_types and not activity.start_latlng
        )

        # Elevation loss from altitude stream
        elevation_loss: int | None = None
        if streams is not None and streams.altitude is not None:
            elevation_loss = calculate_elevation_loss(streams.altitude.data)

        # GPX generation
        gpx_xml: str | None = None
        if streams is not None:
            gpx_xml = generate_gpx(
                streams=streams,
                activity_name=activity.name,
                start_date=activity.start_date,
            )

        return TransformedActivity(
            title=activity.name,
            content=activity.description,
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
            journal_types=journal_types,
            fitness_data_distance=round(activity.distance),
            fitness_data_elevation_gain=round(activity.total_elevation_gain),
            fitness_data_duration=activity.moving_time,
            fitness_data_calories=round(activity.calories)
            if activity.calories is not None
            else None,
            fitness_data_heart_rate_avg=round(activity.average_heartrate)
            if activity.average_heartrate is not None
            else None,
            fitness_data_heart_rate_max=round(activity.max_heartrate)
            if activity.max_heartrate is not None
            else None,
            fitness_data_strava_activity_id=str(activity.id),
            elevation_loss=elevation_loss,
            gpx_xml=gpx_xml,
            version_hash=hashlib.sha256(
                activity.model_dump_json().encode()
            ).hexdigest(),
            strava_athletes=StravaDataTransformer._extract_athletes(activity),
            climbing_indoor=climbing_indoor,
        )

    @staticmethod
    def _extract_athletes(activity: StravaActivity) -> list[dict[str, str | int]]:
        """Extract all athlete data (including group activity participants) from the activity.

        Args:
            activity: Strava API activity response.

        Returns:
            List of athlete dictionaries containing at least an 'id' and optionally a 'name'.
        """
        athletes: list[dict[str, str | int]] = []

        # Extract from segment efforts athletes if any
        # We explicitly don't extract the main activity.athlete as they are the user
        for effort in activity.segment_efforts:
            athlete_info = effort.get("athlete")
            if not isinstance(athlete_info, dict):
                continue

            if "id" in athlete_info:
                athlete_id = athlete_info["id"]
                # Skip if already added
                if any(a["id"] == athlete_id for a in athletes):
                    continue

                athlete_data = {"id": athlete_id}
                firstname = athlete_info.get("firstname")
                lastname = athlete_info.get("lastname")
                if isinstance(firstname, str) and isinstance(lastname, str):
                    athlete_data["name"] = f"{firstname} {lastname}"
                elif isinstance(firstname, str):
                    athlete_data["name"] = firstname
                elif isinstance(lastname, str):
                    athlete_data["name"] = lastname
                athletes.append(athlete_data)

        return athletes
