"""GPX parser utilities for the journal domain.

Uses gpxpy to parse GPX XML strings, extract coordinates for map rendering,
and calculate track statistics (distance, elevation, duration).

All functions are pure and operate on string input, producing dataclass output.
"""

from dataclasses import dataclass

import gpxpy
import gpxpy.gpx
from core_shared.models.journals import GPXParsingError


@dataclass(frozen=True)
class GPXCoordinate:
    """A single coordinate point from a GPX track.

    Attributes:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        elevation: Elevation in metres (None if not recorded)
    """

    latitude: float
    longitude: float
    elevation: float | None


@dataclass(frozen=True)
class GPXStatistics:
    """Computed statistics from a GPX track.

    Attributes:
        distance_2d: Horizontal distance in metres
        distance_3d: Distance accounting for elevation in metres
        elevation_gain: Total uphill metres
        elevation_loss: Total downhill metres (positive value)
        duration_seconds: Total track duration in seconds (None if no timestamps)
    """

    distance_2d: float
    distance_3d: float
    elevation_gain: float
    elevation_loss: float
    duration_seconds: float | None


@dataclass(frozen=True)
class GPXTrackResult:
    """Result of parsing a GPX track.

    Attributes:
        coordinates: Ordered list of track points
        statistics: Computed distance, elevation, and duration statistics
    """

    coordinates: list[GPXCoordinate]
    statistics: GPXStatistics


def parse_gpx_track(gpx_xml: str) -> GPXTrackResult:
    """Parse a GPX XML string and extract coordinates and statistics.

    Uses gpxpy to do the heavy lifting. All track segments across all tracks
    are concatenated into a single coordinate list.

    Args:
        gpx_xml: GPX XML content as a string

    Returns:
        GPXTrackResult containing coordinates and computed statistics

    Raises:
        GPXParsingError: If the input is empty, not valid GPX XML, or
            contains no track points
    """
    if not gpx_xml or not gpx_xml.strip():
        raise GPXParsingError("GPX data cannot be empty")

    try:
        gpx = gpxpy.parse(gpx_xml)
    except Exception as e:
        raise GPXParsingError(f"Failed to parse GPX data: {e}") from e

    # Extract all coordinates from all tracks and segments
    coordinates: list[GPXCoordinate] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                coordinates.append(
                    GPXCoordinate(
                        latitude=point.latitude,
                        longitude=point.longitude,
                        elevation=point.elevation,
                    )
                )

    if not coordinates:
        raise GPXParsingError("No track points found in GPX data")

    # Calculate statistics using gpxpy's built-in methods
    statistics = _calculate_statistics(gpx)

    return GPXTrackResult(coordinates=coordinates, statistics=statistics)


def _calculate_statistics(gpx: gpxpy.gpx.GPX) -> GPXStatistics:
    """Calculate track statistics from a parsed GPX object.

    Args:
        gpx: Parsed gpxpy GPX object

    Returns:
        GPXStatistics with distance, elevation, and duration data
    """
    distance_2d = gpx.length_2d()
    distance_3d = gpx.length_3d()

    uphill, downhill = gpx.get_uphill_downhill()

    # Calculate duration from time bounds
    duration_seconds: float | None = None
    time_bounds = gpx.get_time_bounds()
    if time_bounds.start_time is not None and time_bounds.end_time is not None:
        delta = time_bounds.end_time - time_bounds.start_time
        duration_seconds = delta.total_seconds()

    return GPXStatistics(
        distance_2d=distance_2d,
        distance_3d=distance_3d,
        elevation_gain=uphill,
        elevation_loss=downhill,
        duration_seconds=duration_seconds,
    )
