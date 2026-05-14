"""
Pydantic response models for Strava API v3.

These models parse JSON responses from the Strava API into typed objects
used by ``StravaAPIClient``. Field names mirror the Strava API naming
conventions (snake_case already matches Python).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StravaAthlete(BaseModel):
    """Strava athlete profile from ``GET /athlete``.

    See: https://developers.strava.com/docs/reference/#api-Athletes
    """

    id: int
    firstname: str
    lastname: str
    profile: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None


class StravaActivity(BaseModel):
    """Strava activity summary or detail from ``GET /activities``.

    Covers both the list summary and the single-activity detail response.
    Optional fields are ``None`` when Strava does not provide them (e.g.
    indoor activities have no GPS coordinates, some activities have no HR).

    See: https://developers.strava.com/docs/reference/#api-Activities
    """

    id: int
    name: str
    description: str | None = None
    type: str
    sport_type: str
    start_date: str
    elapsed_time: int
    moving_time: int
    distance: float
    total_elevation_gain: float
    calories: float | None = None
    average_heartrate: float | None = None
    max_heartrate: float | None = None
    start_latlng: list[float] | None = None
    end_latlng: list[float] | None = None
    athlete: dict[str, Any] = {}
    segment_efforts: list[dict[str, Any]] = []


class StravaActivityStream(BaseModel):
    """A single data stream from the Strava Streams API.

    Strava returns streams as individual objects with ``type`` indicating
    the kind of data (latlng, altitude, time, etc.).

    See: https://developers.strava.com/docs/reference/#api-Streams
    """

    type: str
    data: list[Any]
    series_type: str
    original_size: int
    resolution: str


class StravaStreamSet(BaseModel):
    """Container grouping individual streams by type.

    ``from_api_response`` converts the Strava Streams API array response
    into a structured object with named attributes for each stream type
    needed by GPX generation.
    """

    latlng: StravaActivityStream | None = None
    altitude: StravaActivityStream | None = None
    time: StravaActivityStream | None = None

    @classmethod
    def from_api_response(cls, streams: list[dict[str, Any]]) -> StravaStreamSet:
        """Parse the Strava Streams API array response.

        The Strava Streams API returns an array of stream objects, each
        containing a ``type`` field that identifies the stream kind
        (e.g. ``latlng``, ``altitude``, ``time``).

        See: https://developers.strava.com/docs/reference/#api-Streams

        Args:
            streams: Array of stream objects from Strava's
                ``GET /activities/{id}/streams`` response.

        Returns:
            StravaStreamSet with each stream type mapped by name.
        """
        stream_map: dict[str, StravaActivityStream] = {}
        for raw in streams:
            stream = StravaActivityStream.model_validate(raw)
            stream_map[stream.type] = stream

        return cls(
            latlng=stream_map.get("latlng"),
            altitude=stream_map.get("altitude"),
            time=stream_map.get("time"),
        )
