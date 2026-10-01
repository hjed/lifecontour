"""
Unit tests for GpxGenerator.

Tests the conversion of Strava stream data (latlng, altitude, time)
into GPX 1.1 XML format.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from core_shared.product import PRODUCT_NAME

from gpx_generator import generate_gpx
from strava_models import StravaActivityStream, StravaStreamSet

# GPX namespace
GPX_NS = "http://www.topografix.com/GPX/1/1"


def _make_stream(stream_type: str, data: list[Any]) -> StravaActivityStream:
    """Helper to create a StravaActivityStream for testing."""
    return StravaActivityStream(
        type=stream_type,
        data=data,
        series_type="distance",
        original_size=len(data),
        resolution="high",
    )


class TestGpxGeneration:
    """Verify GPX XML generation from Strava streams."""

    def test_generate_gpx_with_all_streams(self) -> None:
        """Full stream set produces GPX with trkpt elements having lat, lon, ele, time."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.8688, 151.2093], [-33.8690, 151.2095]]),
            altitude=_make_stream("altitude", [50.0, 55.0]),
            time=_make_stream("time", [0, 10]),
        )
        result = generate_gpx(
            streams=streams,
            activity_name="Morning Hike",
            start_date="2026-05-01T06:30:00Z",
        )

        assert result is not None
        root = ET.fromstring(result)
        trkpts = root.findall(f".//{{{GPX_NS}}}trkpt")
        assert len(trkpts) == 2

        # Check first track point
        assert trkpts[0].attrib["lat"] == "-33.8688"
        assert trkpts[0].attrib["lon"] == "151.2093"
        ele = trkpts[0].find(f"{{{GPX_NS}}}ele")
        assert ele is not None
        assert ele.text == "50.0"
        time_elem = trkpts[0].find(f"{{{GPX_NS}}}time")
        assert time_elem is not None

    def test_generate_gpx_creator_is_product_name(self) -> None:
        """Downloaded GPX files name the product that generated them."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.8688, 151.2093]]),
            altitude=None,
            time=None,
        )
        result = generate_gpx(
            streams=streams,
            activity_name="Morning Hike",
            start_date="2026-05-01T06:30:00Z",
        )

        assert result is not None
        assert ET.fromstring(result).attrib["creator"] == PRODUCT_NAME

    def test_generate_gpx_without_altitude(self) -> None:
        """Stream set without altitude produces trkpt without <ele> elements."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.8688, 151.2093]]),
            altitude=None,
            time=_make_stream("time", [0]),
        )
        result = generate_gpx(
            streams=streams,
            activity_name="Flat Run",
            start_date="2026-05-01T06:30:00Z",
        )

        assert result is not None
        root = ET.fromstring(result)
        trkpts = root.findall(f".//{{{GPX_NS}}}trkpt")
        assert len(trkpts) == 1
        ele = trkpts[0].find(f"{{{GPX_NS}}}ele")
        assert ele is None

    def test_generate_gpx_without_time(self) -> None:
        """Stream set without time produces trkpt without <time> elements."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.8688, 151.2093]]),
            altitude=_make_stream("altitude", [50.0]),
            time=None,
        )
        result = generate_gpx(
            streams=streams,
            activity_name="No Time Hike",
            start_date="2026-05-01T06:30:00Z",
        )

        assert result is not None
        root = ET.fromstring(result)
        trkpts = root.findall(f".//{{{GPX_NS}}}trkpt")
        assert len(trkpts) == 1
        time_elem = trkpts[0].find(f"{{{GPX_NS}}}time")
        assert time_elem is None

    def test_generate_gpx_empty_latlng(self) -> None:
        """Empty latlng stream returns None."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", []),
            altitude=None,
            time=None,
        )
        result = generate_gpx(
            streams=streams,
            activity_name="Empty",
            start_date="2026-05-01T06:30:00Z",
        )
        assert result is None

    def test_generate_gpx_no_latlng(self) -> None:
        """None latlng stream returns None."""
        streams = StravaStreamSet(latlng=None, altitude=None, time=None)
        result = generate_gpx(
            streams=streams,
            activity_name="No GPS",
            start_date="2026-05-01T06:30:00Z",
        )
        assert result is None

    def test_generate_gpx_activity_name_in_track(self) -> None:
        """Activity name appears in the <name> element of the track."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.8688, 151.2093]]),
            altitude=None,
            time=None,
        )
        result = generate_gpx(
            streams=streams,
            activity_name="Blue Mountains Walk",
            start_date="2026-05-01T06:30:00Z",
        )

        assert result is not None
        root = ET.fromstring(result)
        name_elem = root.find(f".//{{{GPX_NS}}}trk/{{{GPX_NS}}}name")
        assert name_elem is not None
        assert name_elem.text == "Blue Mountains Walk"

    def test_generate_gpx_xml_well_formed(self) -> None:
        """Generated GPX is parseable XML."""
        streams = StravaStreamSet(
            latlng=_make_stream(
                "latlng",
                [[-33.8688, 151.2093], [-33.8690, 151.2095], [-33.8692, 151.2097]],
            ),
            altitude=_make_stream("altitude", [50.0, 55.0, 52.0]),
            time=_make_stream("time", [0, 10, 20]),
        )
        result = generate_gpx(
            streams=streams,
            activity_name="Test Activity",
            start_date="2026-05-01T06:30:00Z",
        )

        assert result is not None
        # Should not raise — valid XML
        root = ET.fromstring(result)
        assert root.tag == f"{{{GPX_NS}}}gpx"

    def test_generate_gpx_time_offsets_from_start_date(self) -> None:
        """Time stream values are offsets from start_date in seconds."""
        streams = StravaStreamSet(
            latlng=_make_stream("latlng", [[-33.8688, 151.2093], [-33.8690, 151.2095]]),
            altitude=None,
            time=_make_stream("time", [0, 60]),
        )
        result = generate_gpx(
            streams=streams,
            activity_name="Timed Run",
            start_date="2026-05-01T06:30:00Z",
        )

        assert result is not None
        root = ET.fromstring(result)
        trkpts = root.findall(f".//{{{GPX_NS}}}trkpt")
        time0 = trkpts[0].find(f"{{{GPX_NS}}}time")
        time1 = trkpts[1].find(f"{{{GPX_NS}}}time")
        assert time0 is not None
        assert time1 is not None
        assert time0.text == "2026-05-01T06:30:00Z"
        assert time1.text == "2026-05-01T06:31:00Z"
