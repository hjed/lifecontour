"""
Unit tests for ElevationCalculator.

Tests the elevation loss calculation from altitude stream data.
Elevation loss is the sum of all negative altitude deltas between
consecutive track points.
"""

from __future__ import annotations

from elevation_calculator import calculate_elevation_loss


class TestElevationLossCalculation:
    """Verify elevation loss calculation from altitude data."""

    def test_elevation_loss_mixed_deltas(self) -> None:
        """Altitude with both ascents and descents sums only negative deltas."""
        # 100→110 (+10), 110→105 (-5), 105→120 (+15), 120→115 (-5)
        altitudes = [100.0, 110.0, 105.0, 120.0, 115.0]
        result = calculate_elevation_loss(altitudes)
        assert result == 10  # 5 + 5

    def test_elevation_loss_only_ascending(self) -> None:
        """Purely ascending altitude produces zero elevation loss."""
        altitudes = [100.0, 110.0, 120.0]
        result = calculate_elevation_loss(altitudes)
        assert result == 0

    def test_elevation_loss_only_descending(self) -> None:
        """Purely descending altitude produces total descent as loss."""
        altitudes = [120.0, 110.0, 100.0]
        result = calculate_elevation_loss(altitudes)
        assert result == 20  # 10 + 10

    def test_elevation_loss_empty_stream(self) -> None:
        """Empty altitude list returns None."""
        result = calculate_elevation_loss([])
        assert result is None

    def test_elevation_loss_single_point(self) -> None:
        """Single altitude point has no deltas, returns 0."""
        result = calculate_elevation_loss([100.0])
        assert result == 0

    def test_elevation_loss_none_input(self) -> None:
        """None input returns None."""
        result = calculate_elevation_loss(None)
        assert result is None

    def test_elevation_loss_two_points_descending(self) -> None:
        """Two-point descent calculates the single delta."""
        altitudes = [100.0, 90.0]
        result = calculate_elevation_loss(altitudes)
        assert result == 10

    def test_elevation_loss_flat_terrain(self) -> None:
        """Flat terrain (constant altitude) produces zero elevation loss."""
        altitudes = [100.0, 100.0, 100.0]
        result = calculate_elevation_loss(altitudes)
        assert result == 0

    def test_elevation_loss_rounds_to_int(self) -> None:
        """Elevation loss is returned as an integer (rounded)."""
        # 100.0→99.7 (-0.3), 99.7→99.2 (-0.5) → 0.8, rounded to 1
        altitudes = [100.0, 99.7, 99.2]
        result = calculate_elevation_loss(altitudes)
        assert isinstance(result, int)
        assert result == 1
