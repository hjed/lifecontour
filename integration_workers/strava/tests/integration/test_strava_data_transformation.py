"""
Integration tests for Strava data transformation.

Round-trip transformation tests using realistic Strava API response
fixtures. These verify the complete pipeline: Strava activity →
type mapping → field transformation → GPX generation → elevation
calculation, producing a fully populated TransformedActivity.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
from core_shared.models.journals import JournalType

from strava_data_transformer import StravaDataTransformer
from strava_models import (
    StravaActivity,
    StravaActivityStream,
    StravaStreamSet,
)

# ------------------------------------------------------------------ #
# Realistic Strava API response fixtures                             #
# ------------------------------------------------------------------ #

GPX_NS = "http://www.topografix.com/GPX/1/1"


def _run_activity() -> StravaActivity:
    """Realistic morning run activity fixture."""
    return StravaActivity.model_validate(
        {
            "id": 10001,
            "name": "Morning Run",
            "description": "Easy recovery run around Centennial Park",
            "type": "Run",
            "sport_type": "Run",
            "start_date": "2026-05-01T06:30:00Z",
            "elapsed_time": 3600,
            "moving_time": 3200,
            "distance": 10234.7,
            "total_elevation_gain": 45.2,
            "calories": 520.0,
            "average_heartrate": 142.0,
            "max_heartrate": 168.0,
            "start_latlng": [-33.8688, 151.2093],
            "end_latlng": [-33.8688, 151.2093],
            "athlete": {"id": 12345},
        }
    )


def _hike_activity() -> StravaActivity:
    """Realistic bushwalk activity fixture."""
    return StravaActivity.model_validate(
        {
            "id": 10002,
            "name": "Blue Mountains Bushwalk",
            "description": "Grand Canyon Track to Evans Lookout",
            "type": "Hike",
            "sport_type": "Hike",
            "start_date": "2026-05-03T08:00:00Z",
            "elapsed_time": 21600,  # 6 hours
            "moving_time": 18000,  # 5 hours
            "distance": 14500.0,
            "total_elevation_gain": 820.7,
            "calories": 1850.0,
            "average_heartrate": 125.0,
            "max_heartrate": 155.0,
            "start_latlng": [-33.7102, 150.3414],
            "end_latlng": [-33.7095, 150.3420],
            "athlete": {"id": 12345},
        }
    )


def _ride_activity_no_gps() -> StravaActivity:
    """Indoor cycling — no GPS data."""
    return StravaActivity.model_validate(
        {
            "id": 10003,
            "name": "Zwift Recovery Ride",
            "description": None,
            "type": "Ride",
            "sport_type": "VirtualRide",
            "start_date": "2026-05-02T18:00:00Z",
            "elapsed_time": 2400,
            "moving_time": 2400,
            "distance": 20000.0,
            "total_elevation_gain": 0.0,
            "calories": 350.0,
            "average_heartrate": None,
            "max_heartrate": None,
            "start_latlng": None,
            "end_latlng": None,
            "athlete": {"id": 12345},
        }
    )


def _kayaking_activity() -> StravaActivity:
    """Sea kayaking activity fixture."""
    return StravaActivity.model_validate(
        {
            "id": 10004,
            "name": "Harbour Paddle",
            "description": "Kayaking from Rose Bay to Manly",
            "type": "Kayaking",
            "sport_type": "Kayaking",
            "start_date": "2026-04-28T07:00:00Z",
            "elapsed_time": 7200,
            "moving_time": 6000,
            "distance": 12000.0,
            "total_elevation_gain": 0.0,
            "calories": 800.0,
            "average_heartrate": 130.0,
            "max_heartrate": 150.0,
            "start_latlng": [-33.8713, 151.2682],
            "end_latlng": [-33.7976, 151.2835],
            "athlete": {"id": 12345},
        }
    )


def _yoga_activity() -> StravaActivity:
    """Unmapped/indoor activity fixture."""
    return StravaActivity.model_validate(
        {
            "id": 10005,
            "name": "Vinyasa Flow",
            "description": "Morning yoga session",
            "type": "Yoga",
            "sport_type": "Yoga",
            "start_date": "2026-05-01T07:00:00Z",
            "elapsed_time": 3600,
            "moving_time": 3600,
            "distance": 0.0,
            "total_elevation_gain": 0.0,
            "calories": 250.0,
            "average_heartrate": 95.0,
            "max_heartrate": 120.0,
            "start_latlng": None,
            "end_latlng": None,
            "athlete": {"id": 12345},
        }
    )


def _sample_streams() -> StravaStreamSet:
    """Create realistic stream data for a short hike segment."""
    return StravaStreamSet(
        latlng=StravaActivityStream(
            type="latlng",
            data=[
                [-33.7102, 150.3414],
                [-33.7105, 150.3418],
                [-33.7108, 150.3420],
                [-33.7110, 150.3422],
                [-33.7112, 150.3425],
            ],
            series_type="distance",
            original_size=5,
            resolution="high",
        ),
        altitude=StravaActivityStream(
            type="altitude",
            data=[1050.0, 1055.0, 1048.0, 1060.0, 1045.0],
            series_type="distance",
            original_size=5,
            resolution="high",
        ),
        time=StravaActivityStream(
            type="time",
            data=[0, 120, 240, 360, 480],
            series_type="distance",
            original_size=5,
            resolution="high",
        ),
    )


# ------------------------------------------------------------------ #
# Integration test class                                             #
# ------------------------------------------------------------------ #


@pytest.mark.integration
class TestStravaDataTransformationRoundTrip:
    """End-to-end transformation tests with realistic fixtures."""

    def test_transform_run_activity(self) -> None:
        """Run activity produces correct title, date range, types, and fitness data."""
        activity = _run_activity()
        result = StravaDataTransformer.transform(activity)

        # Title and content
        assert result.title == "Morning Run"
        assert result.content == "Easy recovery run around Centennial Park"

        # Date range
        assert result.event_date_range.start == datetime(
            2026, 5, 1, 6, 30, 0, tzinfo=UTC
        )
        assert result.event_date_range.end == datetime(2026, 5, 1, 7, 30, 0, tzinfo=UTC)

        # Journal types
        assert result.journal_types == [JournalType.JOGGING, JournalType.FITNESS]

        # Fitness data
        assert result.fitness_data_distance == 10235  # rounded from 10234.7
        assert result.fitness_data_elevation_gain == 45  # rounded from 45.2
        assert result.fitness_data_duration == 3200
        assert result.fitness_data_calories == 520
        assert result.fitness_data_heart_rate_avg == 142
        assert result.fitness_data_heart_rate_max == 168
        assert result.fitness_data_strava_activity_id == "10001"

    def test_transform_hike_activity(self) -> None:
        """Hike produces BUSHWALKING + OUTDOOR_ACTIVITY + FITNESS types and elevation data."""
        activity = _hike_activity()
        result = StravaDataTransformer.transform(activity)

        assert result.journal_types == [
            JournalType.BUSHWALKING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]
        assert result.title == "Blue Mountains Bushwalk"
        assert result.fitness_data_elevation_gain == 821  # rounded from 820.7
        assert result.fitness_data_distance == 14500
        assert result.fitness_data_calories == 1850

    def test_transform_ride_activity_no_gps(self) -> None:
        """Indoor ride maps to FITNESS only, no GPX, null elevation_loss."""
        activity = _ride_activity_no_gps()
        result = StravaDataTransformer.transform(activity)

        assert result.journal_types == [JournalType.FITNESS]
        assert result.content is None
        assert result.elevation_loss is None
        assert result.gpx_xml is None
        assert result.fitness_data_distance == 20000
        assert result.fitness_data_elevation_gain == 0

    def test_transform_kayaking_activity(self) -> None:
        """Kayaking produces correct type hierarchy and fitness data."""
        activity = _kayaking_activity()
        result = StravaDataTransformer.transform(activity)

        assert result.journal_types == [
            JournalType.KAYAKING,
            JournalType.OUTDOOR_ACTIVITY,
            JournalType.FITNESS,
        ]
        assert result.title == "Harbour Paddle"
        assert result.fitness_data_distance == 12000
        assert result.fitness_data_duration == 6000
        assert result.fitness_data_calories == 800

    def test_transform_unmapped_activity(self) -> None:
        """Yoga (mapped to FITNESS) produces correct fields."""
        activity = _yoga_activity()
        result = StravaDataTransformer.transform(activity)

        assert result.journal_types == [JournalType.FITNESS]
        assert result.title == "Vinyasa Flow"
        assert result.fitness_data_distance == 0
        assert result.fitness_data_elevation_gain == 0
        assert result.fitness_data_heart_rate_avg == 95
        assert result.fitness_data_heart_rate_max == 120

    def test_transform_activity_with_streams(self) -> None:
        """Activity + full stream set → GPX generated, elevation_loss calculated."""
        activity = _hike_activity()
        streams = _sample_streams()
        result = StravaDataTransformer.transform(activity, streams=streams)

        # GPX generated
        assert result.gpx_xml is not None
        root = ET.fromstring(result.gpx_xml)
        trkpts = root.findall(f".//{{{GPX_NS}}}trkpt")
        assert len(trkpts) == 5

        # Track name
        name_elem = root.find(f".//{{{GPX_NS}}}trk/{{{GPX_NS}}}name")
        assert name_elem is not None
        assert name_elem.text == "Blue Mountains Bushwalk"

        # Elevation loss calculated from stream
        # 1050→1055 (+5), 1055→1048 (-7), 1048→1060 (+12), 1060→1045 (-15)
        # Loss = 7 + 15 = 22
        assert result.elevation_loss == 22

    def test_transform_activity_without_streams(self) -> None:
        """Activity without streams → null GPX, null elevation_loss."""
        activity = _hike_activity()
        result = StravaDataTransformer.transform(activity, streams=None)

        assert result.gpx_xml is None
        assert result.elevation_loss is None
        # Other fields still populated
        assert result.title == "Blue Mountains Bushwalk"
        assert result.fitness_data_distance == 14500
