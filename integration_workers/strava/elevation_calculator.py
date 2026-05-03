"""
Elevation loss calculator for Strava altitude streams.

Computes elevation loss (total descent) from a series of altitude
values by summing all negative deltas between consecutive points.
This value is not provided directly by the Strava API and must be
derived from the altitude stream fetched for GPX generation.
"""

from __future__ import annotations


def calculate_elevation_loss(altitudes: list[float] | None) -> int | None:
    """Calculate total elevation loss from an altitude stream.

    Elevation loss is the sum of all negative altitude changes between
    consecutive track points. This gives the total metres descended
    during the activity.

    Args:
        altitudes: List of altitude values in metres, ordered by time.
            ``None`` or empty list indicates no altitude data is available.

    Returns:
        Total elevation loss in metres as an integer (rounded), or
        ``None`` when no altitude data is available.
    """
    if altitudes is None or len(altitudes) == 0:
        return None

    if len(altitudes) == 1:
        return 0

    total_loss = 0.0
    for i in range(1, len(altitudes)):
        delta = altitudes[i] - altitudes[i - 1]
        if delta < 0:
            total_loss += abs(delta)

    return round(total_loss)
