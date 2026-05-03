"""
GPX generator for Strava activity streams.

Converts Strava Streams API data (latlng, altitude, time) into GPX 1.1
format XML. The generated GPX is stored as a ``Route`` entity linked to
the journal in later sync phases.

GPX 1.1 Specification: https://www.topografix.com/gpx/1/1/
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

from strava_models import StravaStreamSet

_GPX_NS = "http://www.topografix.com/GPX/1/1"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_GPX_SCHEMA = (
    "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd"
)


def generate_gpx(
    *,
    streams: StravaStreamSet,
    activity_name: str,
    start_date: str,
) -> str | None:
    """Generate GPX 1.1 XML from Strava stream data.

    Args:
        streams: Stream data containing latlng, altitude, and/or time arrays.
        activity_name: Name of the activity (used as track name).
        start_date: ISO 8601 start timestamp for the activity
            (e.g. ``"2026-05-01T06:30:00Z"``). Time stream values are
            offsets in seconds from this timestamp.

    Returns:
        GPX XML string, or ``None`` when no GPS data is available
        (latlng is None or empty).
    """
    # No GPS data available
    if streams.latlng is None or len(streams.latlng.data) == 0:
        return None

    # Parse start time
    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))

    # Register namespace to avoid ns0: prefixes in output
    ET.register_namespace("", _GPX_NS)
    ET.register_namespace("xsi", _XSI_NS)

    # Build GPX root
    gpx = ET.Element(
        f"{{{_GPX_NS}}}gpx",
        {
            "version": "1.1",
            "creator": "PersonalManagementSystem",
            f"{{{_XSI_NS}}}schemaLocation": _GPX_SCHEMA,
        },
    )

    # Track
    trk = ET.SubElement(gpx, f"{{{_GPX_NS}}}trk")
    name_elem = ET.SubElement(trk, f"{{{_GPX_NS}}}name")
    name_elem.text = activity_name

    # Track segment
    trkseg = ET.SubElement(trk, f"{{{_GPX_NS}}}trkseg")

    # Extract optional data arrays
    altitudes = streams.altitude.data if streams.altitude else None
    times = streams.time.data if streams.time else None

    for i, latlng in enumerate(streams.latlng.data):
        lat, lon = latlng
        trkpt = ET.SubElement(
            trkseg,
            f"{{{_GPX_NS}}}trkpt",
            {"lat": str(lat), "lon": str(lon)},
        )

        # Elevation
        if altitudes is not None and i < len(altitudes):
            ele = ET.SubElement(trkpt, f"{{{_GPX_NS}}}ele")
            ele.text = str(altitudes[i])

        # Time
        if times is not None and i < len(times):
            time_elem = ET.SubElement(trkpt, f"{{{_GPX_NS}}}time")
            point_dt = start_dt + timedelta(seconds=times[i])
            time_elem.text = _format_utc_time(point_dt)

    # Serialize to string
    return ET.tostring(gpx, encoding="unicode", xml_declaration=False)


def _format_utc_time(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC string with Z suffix.

    Args:
        dt: Datetime to format (should be timezone-aware UTC).

    Returns:
        ISO 8601 string like ``"2026-05-01T06:30:00Z"``.
    """
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
