"""
Unit tests for StravaDataTransformer.

Tests activity type mapping from Strava types to journal type hierarchy
and field transformation from Strava activity fields to journal domain fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import JournalType

from strava_data_transformer import StravaDataTransformer
from strava_models import StravaActivity, StravaActivityStream, StravaStreamSet


def _make_activity(**overrides: Any) -> StravaActivity:
    """Create a StravaActivity with sensible defaults, overridable per-test."""
    defaults = {
        "id": 12345,
        "name": "Test Activity",
        "description": None,
        "type": "Run",
        "sport_type": "Run",
        "start_date": "2026-05-01T06:30:00Z",
        "elapsed_time": 3600,
        "moving_time": 3200,
        "distance": 10000.0,
        "total_elevation_gain": 150.0,
        "calories": None,
        "average_heartrate": None,
        "max_heartrate": None,
        "start_latlng": None,
        "end_latlng": None,
        "athlete": {"id": 999},
    }
    defaults.update(overrides)
    return StravaActivity.model_validate(defaults)


def _make_stream(stream_type: str, data: list[Any]) -> StravaActivityStream:
    """Helper to create a StravaActivityStream."""
    return StravaActivityStream(
        type=stream_type,
        data=data,
        series_type="distance",
        original_size=len(data),
        resolution="high",
    )


class TestTypeMapping:
    """Verify Strava activity type → journal type mapping per the product spec."""

    def test_run_maps_to_jogging_fitness(self) -> None:
        """Run → [JOGGING, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Run")
        assert result == [JournalType.JOGGING, JournalType.FITNESS]

    def test_trail_run_maps_to_jogging_outdoor_fitness(self) -> None:
        """TrailRun → [JOGGING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("TrailRun")
        assert result == [
            JournalType.JOGGING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_hike_maps_to_bushwalking_outdoor_fitness(self) -> None:
        """Hike → [BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Hike")
        assert result == [
            JournalType.BUSHWALKING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_walk_maps_to_bushwalking_outdoor_fitness(self) -> None:
        """Walk → [BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Walk")
        assert result == [
            JournalType.BUSHWALKING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_ride_maps_to_fitness(self) -> None:
        """Ride → [FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Ride")
        assert result == [JournalType.FITNESS]

    def test_mountain_bike_ride_maps_to_outdoor_fitness(self) -> None:
        """MountainBikeRide → [OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("MountainBikeRide")
        assert result == [JournalType.OUTDOOR_ACTIVITY, JournalType.FITNESS]

    def test_swim_maps_to_fitness(self) -> None:
        """Swim → [FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Swim")
        assert result == [JournalType.FITNESS]

    def test_kayaking_maps_to_kayaking_outdoor_fitness(self) -> None:
        """Kayaking → [KAYAKING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Kayaking")
        assert result == [
            JournalType.KAYAKING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_canoeing_maps_to_canoeing_outdoor_fitness(self) -> None:
        """Canoeing → [CANOEING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Canoeing")
        assert result == [
            JournalType.CANOEING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_rock_climbing_maps_to_climbing_abseiling_outdoor_fitness(self) -> None:
        """RockClimbing → [CLIMBING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("RockClimbing")
        assert result == [
            JournalType.CLIMBING,
            JournalType.ABSEILING_TRIP,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_nordic_ski_maps_to_xc_skiing_bushwalking_outdoor_fitness(self) -> None:
        """NordicSki → [CROSS_COUNTRY_SKIING, BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("NordicSki")
        assert result == [
            JournalType.CROSS_COUNTRY_SKIING,
            JournalType.BUSHWALKING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_alpine_ski_maps_to_downhill_skiing_outdoor_fitness(self) -> None:
        """AlpineSki → [DOWNHILL_SKIING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("AlpineSki")
        assert result == [
            JournalType.DOWNHILL_SKIING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_snowshoe_maps_to_bushwalking_outdoor_fitness(self) -> None:
        """Snowshoe → [BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Snowshoe")
        assert result == [
            JournalType.BUSHWALKING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]

    def test_rowing_maps_to_fitness(self) -> None:
        """Rowing → [FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Rowing")
        assert result == [JournalType.FITNESS]

    def test_surfing_maps_to_fitness(self) -> None:
        """Surfing → [FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Surfing")
        assert result == [JournalType.FITNESS]

    def test_yoga_maps_to_fitness(self) -> None:
        """Yoga → [FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Yoga")
        assert result == [JournalType.FITNESS]

    def test_other_maps_to_fitness(self) -> None:
        """Other → [FITNESS]."""
        result = StravaDataTransformer.map_activity_types("Other")
        assert result == [JournalType.FITNESS]

    def test_unknown_type_defaults_to_fitness(self) -> None:
        """Unmapped Strava types default to FITNESS only."""
        result = StravaDataTransformer.map_activity_types("Handstand")
        assert result == [JournalType.FITNESS]


class TestFieldTransformation:
    """Verify Strava → journal field mapping per the product spec."""

    def test_title_from_name(self) -> None:
        """activity.name → title."""
        activity = _make_activity(name="Morning Run")
        result = StravaDataTransformer.transform(activity)
        assert result.title == "Morning Run"

    def test_content_from_description(self) -> None:
        """activity.description → content."""
        activity = _make_activity(description="Easy recovery run")
        result = StravaDataTransformer.transform(activity)
        assert result.content == "Easy recovery run"

    def test_content_null_when_no_description(self) -> None:
        """activity.description=None → content=None."""
        activity = _make_activity(description=None)
        result = StravaDataTransformer.transform(activity)
        assert result.content is None

    def test_event_date_range_from_start_date_and_elapsed_time(self) -> None:
        """start_date + elapsed_time → EventDateRange."""
        activity = _make_activity(
            start_date="2026-05-01T06:30:00Z",
            elapsed_time=3600,
        )
        result = StravaDataTransformer.transform(activity)

        expected_start = datetime(2026, 5, 1, 6, 30, 0, tzinfo=UTC)
        expected_end = datetime(2026, 5, 1, 7, 30, 0, tzinfo=UTC)
        assert result.event_date_range.start == expected_start
        assert result.event_date_range.end == expected_end

    def test_fitness_data_distance(self) -> None:
        """activity.distance (float metres) → fitness_data.distance (int)."""
        activity = _make_activity(distance=10500.7)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_distance == 10501

    def test_fitness_data_elevation_gain(self) -> None:
        """activity.total_elevation_gain → fitness_data.elevation_gain (int)."""
        activity = _make_activity(total_elevation_gain=250.8)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_elevation_gain == 251

    def test_fitness_data_duration(self) -> None:
        """activity.moving_time → fitness_data.duration."""
        activity = _make_activity(moving_time=3200)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_duration == 3200

    def test_fitness_data_calories(self) -> None:
        """activity.calories → fitness_data.calories (int)."""
        activity = _make_activity(calories=650.7)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_calories == 651

    def test_fitness_data_heart_rate_avg(self) -> None:
        """activity.average_heartrate → fitness_data.heart_rate_avg (int)."""
        activity = _make_activity(average_heartrate=145.3)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_heart_rate_avg == 145

    def test_fitness_data_heart_rate_max(self) -> None:
        """activity.max_heartrate → fitness_data.heart_rate_max (int)."""
        activity = _make_activity(max_heartrate=175.8)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_heart_rate_max == 176

    def test_fitness_data_strava_activity_id(self) -> None:
        """activity.id → fitness_data.strava_activity_id (str)."""
        activity = _make_activity(id=98765)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_strava_activity_id == "98765"

    def test_null_optional_fields(self) -> None:
        """Null calories, HR → null fitness_data fields."""
        activity = _make_activity(
            calories=None,
            average_heartrate=None,
            max_heartrate=None,
        )
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_calories is None
        assert result.fitness_data_heart_rate_avg is None
        assert result.fitness_data_heart_rate_max is None

    def test_elevation_loss_from_altitude_stream(self) -> None:
        """Altitude stream → fitness_data.elevation_loss calculated."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.0, 151.0], [-33.1, 151.1]]),
            altitude=_make_stream("altitude", [100.0, 90.0]),
            time=_make_stream("time", [0, 10]),
        )
        activity = _make_activity()
        result = StravaDataTransformer.transform(activity, streams=streams)
        assert result.elevation_loss == 10

    def test_elevation_loss_null_without_streams(self) -> None:
        """No streams → elevation_loss = None."""
        activity = _make_activity()
        result = StravaDataTransformer.transform(activity, streams=None)
        assert result.elevation_loss is None

    def test_gpx_generated_with_streams(self) -> None:
        """Streams with GPS data → gpx_xml populated."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.0, 151.0]]),
            altitude=_make_stream("altitude", [100.0]),
            time=_make_stream("time", [0]),
        )
        activity = _make_activity()
        result = StravaDataTransformer.transform(activity, streams=streams)
        assert result.gpx_xml is not None
        assert "<trkpt" in result.gpx_xml

    def test_gpx_null_without_streams(self) -> None:
        """No streams → gpx_xml = None."""
        activity = _make_activity()
        result = StravaDataTransformer.transform(activity, streams=None)
        assert result.gpx_xml is None

    def test_journal_types_from_activity_type(self) -> None:
        """activity.type → journal_types list."""
        activity = _make_activity(type="Hike")
        result = StravaDataTransformer.transform(activity)
        assert JournalType.BUSHWALKING in result.journal_types
        assert JournalType.OUTDOOR_ACTIVITY in result.journal_types
        assert JournalType.FITNESS in result.journal_types

    def test_zero_distance_maps_to_zero(self) -> None:
        """Zero distance maps to 0, not None."""
        activity = _make_activity(distance=0.0)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_distance == 0

    def test_zero_elevation_gain_maps_to_zero(self) -> None:
        """Zero elevation gain maps to 0, not None."""
        activity = _make_activity(total_elevation_gain=0.0)
        result = StravaDataTransformer.transform(activity)
        assert result.fitness_data_elevation_gain == 0
