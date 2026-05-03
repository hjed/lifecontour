"""
Unit tests for Strava Pydantic response models.

Tests parsing of Strava API JSON responses into typed models used
by ``StravaAPIClient``.
"""

from __future__ import annotations

import pytest

from strava_models import (
    StravaActivity,
    StravaActivityStream,
    StravaAthlete,
    StravaStreamSet,
)


class TestStravaAthlete:
    """Parse ``/athlete`` responses."""

    def test_parse_minimal_athlete(self) -> None:
        """Parsing a minimal athlete response extracts required fields."""
        data = {
            "id": 12345,
            "firstname": "Jane",
            "lastname": "Doe",
        }
        athlete = StravaAthlete.model_validate(data)

        assert athlete.id == 12345
        assert athlete.firstname == "Jane"
        assert athlete.lastname == "Doe"
        assert athlete.profile is None
        assert athlete.city is None

    def test_parse_full_athlete(self) -> None:
        """Parsing a fully populated athlete response extracts all fields."""
        data = {
            "id": 99999,
            "firstname": "John",
            "lastname": "Smith",
            "profile": "https://example.com/avatar.jpg",
            "city": "Sydney",
            "state": "NSW",
            "country": "Australia",
        }
        athlete = StravaAthlete.model_validate(data)

        assert athlete.id == 99999
        assert athlete.profile == "https://example.com/avatar.jpg"
        assert athlete.city == "Sydney"
        assert athlete.state == "NSW"
        assert athlete.country == "Australia"


class TestStravaActivity:
    """Parse ``/activities`` and ``/activities/{id}`` responses."""

    def test_parse_full_activity_with_fitness_data(self) -> None:
        """Parsing an activity with all fitness fields extracts them correctly."""
        data = {
            "id": 1001,
            "name": "Morning Run",
            "description": "Easy recovery run",
            "type": "Run",
            "sport_type": "Run",
            "start_date": "2026-05-01T06:30:00Z",
            "elapsed_time": 3600,
            "moving_time": 3200,
            "distance": 10000.0,
            "total_elevation_gain": 150.5,
            "calories": 650.0,
            "average_heartrate": 145.0,
            "max_heartrate": 175.0,
            "start_latlng": [-33.8688, 151.2093],
            "end_latlng": [-33.8700, 151.2100],
            "athlete": {"id": 12345},
        }
        activity = StravaActivity.model_validate(data)

        assert activity.id == 1001
        assert activity.name == "Morning Run"
        assert activity.description == "Easy recovery run"
        assert activity.type == "Run"
        assert activity.sport_type == "Run"
        assert activity.start_date == "2026-05-01T06:30:00Z"
        assert activity.elapsed_time == 3600
        assert activity.moving_time == 3200
        assert activity.distance == 10000.0
        assert activity.total_elevation_gain == 150.5
        assert activity.calories == 650.0
        assert activity.average_heartrate == 145.0
        assert activity.max_heartrate == 175.0
        assert activity.start_latlng == [-33.8688, 151.2093]
        assert activity.end_latlng == [-33.8700, 151.2100]
        assert activity.athlete["id"] == 12345

    def test_parse_activity_with_null_optional_fields(self) -> None:
        """Activities without GPS/HR data have null optional fields."""
        data = {
            "id": 1002,
            "name": "Indoor Ride",
            "type": "Ride",
            "sport_type": "VirtualRide",
            "start_date": "2026-05-01T18:00:00Z",
            "elapsed_time": 1800,
            "moving_time": 1800,
            "distance": 0.0,
            "total_elevation_gain": 0.0,
            "athlete": {"id": 12345},
        }
        activity = StravaActivity.model_validate(data)

        assert activity.description is None
        assert activity.calories is None
        assert activity.average_heartrate is None
        assert activity.max_heartrate is None
        assert activity.start_latlng is None
        assert activity.end_latlng is None

    def test_parse_activity_missing_required_field_raises(self) -> None:
        """Activities missing required fields raise a validation error."""
        data = {
            # Missing 'id' and 'name'
            "type": "Run",
            "sport_type": "Run",
            "start_date": "2026-05-01T06:30:00Z",
            "elapsed_time": 3600,
            "moving_time": 3200,
            "distance": 10000.0,
            "total_elevation_gain": 150.5,
            "athlete": {"id": 12345},
        }
        with pytest.raises(ValueError):
            StravaActivity.model_validate(data)


class TestStravaActivityStream:
    """Parse individual stream objects from Strava Streams API."""

    def test_parse_latlng_stream(self) -> None:
        """Parsing a latlng stream extracts coordinate pairs."""
        data = {
            "type": "latlng",
            "data": [[-33.8688, 151.2093], [-33.8690, 151.2095]],
            "series_type": "distance",
            "original_size": 2,
            "resolution": "high",
        }
        stream = StravaActivityStream.model_validate(data)

        assert stream.type == "latlng"
        assert len(stream.data) == 2
        assert stream.data[0] == [-33.8688, 151.2093]
        assert stream.series_type == "distance"
        assert stream.original_size == 2
        assert stream.resolution == "high"

    def test_parse_altitude_stream(self) -> None:
        """Parsing an altitude stream extracts elevation values."""
        data = {
            "type": "altitude",
            "data": [10.0, 12.5, 11.0, 15.0],
            "series_type": "distance",
            "original_size": 4,
            "resolution": "high",
        }
        stream = StravaActivityStream.model_validate(data)

        assert stream.type == "altitude"
        assert stream.data == [10.0, 12.5, 11.0, 15.0]

    def test_parse_time_stream(self) -> None:
        """Parsing a time stream extracts elapsed seconds."""
        data = {
            "type": "time",
            "data": [0, 10, 20, 30],
            "series_type": "distance",
            "original_size": 4,
            "resolution": "high",
        }
        stream = StravaActivityStream.model_validate(data)

        assert stream.type == "time"
        assert stream.data == [0, 10, 20, 30]


class TestStravaStreamSet:
    """Parse combined stream responses from ``GET /activities/{id}/streams``."""

    def test_parse_stream_set_from_api_response(self) -> None:
        """Parsing Strava's stream array response groups by stream type."""
        api_response = [
            {
                "type": "latlng",
                "data": [[-33.8688, 151.2093], [-33.8690, 151.2095]],
                "series_type": "distance",
                "original_size": 2,
                "resolution": "high",
            },
            {
                "type": "altitude",
                "data": [10.0, 12.5],
                "series_type": "distance",
                "original_size": 2,
                "resolution": "high",
            },
            {
                "type": "time",
                "data": [0, 10],
                "series_type": "distance",
                "original_size": 2,
                "resolution": "high",
            },
        ]
        stream_set = StravaStreamSet.from_api_response(api_response)

        assert stream_set.latlng is not None
        assert stream_set.altitude is not None
        assert stream_set.time is not None
        assert len(stream_set.latlng.data) == 2
        assert len(stream_set.altitude.data) == 2
        assert len(stream_set.time.data) == 2

    def test_parse_stream_set_with_missing_streams(self) -> None:
        """Partial stream responses leave missing streams as None."""
        api_response = [
            {
                "type": "latlng",
                "data": [[-33.8688, 151.2093]],
                "series_type": "distance",
                "original_size": 1,
                "resolution": "high",
            },
        ]
        stream_set = StravaStreamSet.from_api_response(api_response)

        assert stream_set.latlng is not None
        assert stream_set.altitude is None
        assert stream_set.time is None

    def test_parse_empty_stream_response(self) -> None:
        """Empty stream response yields all-None stream set."""
        stream_set = StravaStreamSet.from_api_response([])

        assert stream_set.latlng is None
        assert stream_set.altitude is None
        assert stream_set.time is None
