"""Unit tests for GPX parser utilities.

Tests the gpx_parser module which uses gpxpy to parse GPX XML strings,
extract coordinates, and calculate track statistics.
"""

import pytest

from app.core.journal.models.exceptions import GPXParsingError
from app.core.journal.utils.gpx_parser import (
    GPXCoordinate,
    GPXStatistics,
    GPXTrackResult,
    parse_gpx_track,
)


def _build_gpx_with_points(
    points: list[dict[str, float | str | None]],
) -> str:
    """Build a minimal GPX XML string with the given track points.

    Each point dict may contain: lat, lon, ele, time.
    """
    trkpts = []
    for pt in points:
        ele_tag = f"<ele>{pt['ele']}</ele>" if pt.get("ele") is not None else ""
        time_tag = f"<time>{pt['time']}</time>" if pt.get("time") else ""
        trkpts.append(
            f'<trkpt lat="{pt["lat"]}" lon="{pt["lon"]}">{ele_tag}{time_tag}</trkpt>'
        )
    trkpt_xml = "\n        ".join(trkpts)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Test Track</name>
    <trkseg>
        {trkpt_xml}
    </trkseg>
  </trk>
</gpx>"""


@pytest.mark.unit
class TestParseGPXTrack:
    """Test parse_gpx_track function."""

    def test_parse_simple_track(self):
        """Test extracting coordinates from a minimal GPX with 3 points."""
        gpx_xml = _build_gpx_with_points(
            [
                {"lat": -33.8688, "lon": 151.2093, "ele": 10.0},
                {"lat": -33.8690, "lon": 151.2095, "ele": 15.0},
                {"lat": -33.8692, "lon": 151.2097, "ele": 12.0},
            ]
        )

        result = parse_gpx_track(gpx_xml)

        assert isinstance(result, GPXTrackResult)
        assert len(result.coordinates) == 3
        assert result.coordinates[0].latitude == pytest.approx(-33.8688)
        assert result.coordinates[0].longitude == pytest.approx(151.2093)
        assert result.coordinates[0].elevation == pytest.approx(10.0)
        assert result.coordinates[1].latitude == pytest.approx(-33.8690)
        assert result.coordinates[1].longitude == pytest.approx(151.2095)
        assert result.coordinates[1].elevation == pytest.approx(15.0)
        assert result.coordinates[2].latitude == pytest.approx(-33.8692)
        assert result.coordinates[2].longitude == pytest.approx(151.2097)
        assert result.coordinates[2].elevation == pytest.approx(12.0)

    def test_parse_track_with_elevation(self):
        """Test that elevation values are preserved in coordinates."""
        gpx_xml = _build_gpx_with_points(
            [
                {"lat": -33.0, "lon": 151.0, "ele": 100.0},
                {"lat": -33.001, "lon": 151.001, "ele": 200.0},
                {"lat": -33.002, "lon": 151.002, "ele": 150.0},
            ]
        )

        result = parse_gpx_track(gpx_xml)

        assert result.coordinates[0].elevation == pytest.approx(100.0)
        assert result.coordinates[1].elevation == pytest.approx(200.0)
        assert result.coordinates[2].elevation == pytest.approx(150.0)

    def test_parse_track_without_elevation(self):
        """Test that missing elevation is returned as None."""
        gpx_xml = _build_gpx_with_points(
            [
                {"lat": -33.0, "lon": 151.0},
                {"lat": -33.001, "lon": 151.001},
            ]
        )

        result = parse_gpx_track(gpx_xml)

        assert result.coordinates[0].elevation is None
        assert result.coordinates[1].elevation is None

    def test_parse_track_statistics_distance(self):
        """Test that 2D and 3D distances are computed and positive."""
        # Two points separated by a meaningful distance (~157m apart)
        gpx_xml = _build_gpx_with_points(
            [
                {"lat": -33.8688, "lon": 151.2093, "ele": 10.0},
                {"lat": -33.8700, "lon": 151.2100, "ele": 20.0},
            ]
        )

        result = parse_gpx_track(gpx_xml)

        assert result.statistics.distance_2d > 0
        assert result.statistics.distance_3d > 0
        # 3D distance should be >= 2D distance (includes elevation change)
        assert result.statistics.distance_3d >= result.statistics.distance_2d

    def test_parse_track_statistics_elevation(self):
        """Test that elevation gain and loss are computed correctly."""
        # Use larger elevation differences to exceed gpxpy's smoothing threshold.
        # gpxpy applies a threshold (~10m by default) to filter GPS noise.
        gpx_xml = _build_gpx_with_points(
            [
                {"lat": -33.0, "lon": 151.0, "ele": 0.0},
                {"lat": -33.005, "lon": 151.005, "ele": 200.0},
                {"lat": -33.010, "lon": 151.010, "ele": 50.0},
            ]
        )

        result = parse_gpx_track(gpx_xml)

        # Elevation gain should reflect the uphill section (0 -> 200 = 200m)
        assert result.statistics.elevation_gain > 0
        # Elevation loss should reflect the downhill section (200 -> 50 = 150m)
        assert result.statistics.elevation_loss > 0
        # Gain should be greater than loss in this profile
        assert result.statistics.elevation_gain > result.statistics.elevation_loss

    def test_parse_track_statistics_duration(self):
        """Test duration calculated from timestamps."""
        gpx_xml = _build_gpx_with_points(
            [
                {
                    "lat": -33.0,
                    "lon": 151.0,
                    "ele": 10.0,
                    "time": "2024-01-15T10:00:00Z",
                },
                {
                    "lat": -33.001,
                    "lon": 151.001,
                    "ele": 15.0,
                    "time": "2024-01-15T10:30:00Z",
                },
                {
                    "lat": -33.002,
                    "lon": 151.002,
                    "ele": 12.0,
                    "time": "2024-01-15T11:00:00Z",
                },
            ]
        )

        result = parse_gpx_track(gpx_xml)

        # 1 hour = 3600 seconds
        assert result.statistics.duration_seconds == pytest.approx(3600.0)

    def test_parse_track_no_timestamps(self):
        """Test duration is None when no timestamps are present."""
        gpx_xml = _build_gpx_with_points(
            [
                {"lat": -33.0, "lon": 151.0, "ele": 10.0},
                {"lat": -33.001, "lon": 151.001, "ele": 15.0},
            ]
        )

        result = parse_gpx_track(gpx_xml)

        assert result.statistics.duration_seconds is None

    def test_parse_empty_string_raises_error(self):
        """Test that empty string raises GPXParsingError."""
        with pytest.raises(GPXParsingError, match="GPX data cannot be empty"):
            parse_gpx_track("")

    def test_parse_whitespace_only_raises_error(self):
        """Test that whitespace-only string raises GPXParsingError."""
        with pytest.raises(GPXParsingError, match="GPX data cannot be empty"):
            parse_gpx_track("   \n  ")

    def test_parse_invalid_xml_raises_error(self):
        """Test that malformed XML raises GPXParsingError."""
        with pytest.raises(GPXParsingError, match="Failed to parse GPX"):
            parse_gpx_track("<not valid xml>>>")

    def test_parse_gpx_no_tracks_raises_error(self):
        """Test that valid GPX with no tracks raises GPXParsingError."""
        gpx_xml = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="-33.0" lon="151.0">
    <name>Waypoint Only</name>
  </wpt>
</gpx>"""
        with pytest.raises(GPXParsingError, match="No track points found"):
            parse_gpx_track(gpx_xml)

    def test_parse_multi_segment_track(self):
        """Test that multiple segments in one track are concatenated."""
        gpx_xml = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Multi-Segment Track</name>
    <trkseg>
      <trkpt lat="-33.0" lon="151.0"><ele>10</ele></trkpt>
      <trkpt lat="-33.001" lon="151.001"><ele>20</ele></trkpt>
    </trkseg>
    <trkseg>
      <trkpt lat="-33.002" lon="151.002"><ele>30</ele></trkpt>
      <trkpt lat="-33.003" lon="151.003"><ele>25</ele></trkpt>
    </trkseg>
  </trk>
</gpx>"""

        result = parse_gpx_track(gpx_xml)

        assert len(result.coordinates) == 4
        assert result.coordinates[0].latitude == pytest.approx(-33.0)
        assert result.coordinates[3].latitude == pytest.approx(-33.003)


@pytest.mark.unit
class TestGPXDataclasses:
    """Test GPX dataclass properties."""

    def test_gpx_coordinate_equality(self):
        """Test GPXCoordinate equality comparison."""
        c1 = GPXCoordinate(latitude=-33.0, longitude=151.0, elevation=10.0)
        c2 = GPXCoordinate(latitude=-33.0, longitude=151.0, elevation=10.0)
        assert c1.latitude == pytest.approx(c2.latitude)
        assert c1.longitude == pytest.approx(c2.longitude)
        if c1.elevation is not None and c2.elevation is not None:
            assert c1.elevation == pytest.approx(c2.elevation)
        else:
            assert c1.elevation == c2.elevation

    def test_gpx_coordinate_none_elevation(self):
        """Test GPXCoordinate with None elevation."""
        coord = GPXCoordinate(latitude=-33.0, longitude=151.0, elevation=None)
        assert coord.elevation is None

    def test_gpx_statistics_fields(self):
        """Test GPXStatistics has all expected fields."""
        stats = GPXStatistics(
            distance_2d=1000.0,
            distance_3d=1050.0,
            elevation_gain=100.0,
            elevation_loss=50.0,
            duration_seconds=3600.0,
        )
        assert stats.distance_2d == pytest.approx(1000.0)
        assert stats.distance_3d == pytest.approx(1050.0)
        assert stats.elevation_gain == pytest.approx(100.0)
        assert stats.elevation_loss == pytest.approx(50.0)
        assert stats.duration_seconds == pytest.approx(3600.0)

    def test_gpx_track_result_fields(self):
        """Test GPXTrackResult holds coordinates and statistics."""
        coords = [GPXCoordinate(latitude=-33.0, longitude=151.0, elevation=10.0)]
        stats = GPXStatistics(
            distance_2d=0.0,
            distance_3d=0.0,
            elevation_gain=0.0,
            elevation_loss=0.0,
            duration_seconds=None,
        )
        result = GPXTrackResult(coordinates=coords, statistics=stats)
        assert len(result.coordinates) == 1
        assert result.statistics.duration_seconds is None
