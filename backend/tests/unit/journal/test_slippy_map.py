"""Unit tests for the slippy-map projection helpers.

Pure Web-Mercator geometry used by the outdoor-logbook PDF's GPX map images:
projecting coordinates to global pixels, choosing the zoom that fits a track
inside a bounded tile grid, and enumerating the tiles that grid needs.

The reference pixel/tile values below come from the OpenStreetMap wiki's
slippy-map tilename formula, so they pin this module against the same
projection the tile server itself uses.
"""

import pytest

from app.core.journal.utils.slippy_map import (
    TILE_SIZE,
    TrackBounds,
    choose_zoom,
    lonlat_to_pixel,
    tile_span,
)

# Blue Mountains, NSW — its tile at zoom 13 per the OSM tilename formula.
_BLUE_MOUNTAINS_LAT = -33.7
_BLUE_MOUNTAINS_LON = 150.3
_BLUE_MOUNTAINS_Z13_TILE = (7516, 4911)


@pytest.mark.unit
class TestLonLatToPixel:
    """Test lonlat_to_pixel."""

    def test_lonlat_to_pixel_at_zoom_zero_centres_null_island(self):
        """At zoom 0 the whole world is one tile and (0, 0) is its centre."""
        px, py = lonlat_to_pixel(0.0, 0.0, 0)

        assert px == pytest.approx(TILE_SIZE / 2)
        assert py == pytest.approx(TILE_SIZE / 2)

    def test_lonlat_to_pixel_matches_known_osm_tile(self):
        """The projected pixel falls inside the coordinate's real OSM tile."""
        px, py = lonlat_to_pixel(_BLUE_MOUNTAINS_LAT, _BLUE_MOUNTAINS_LON, 13)

        assert (int(px // TILE_SIZE), int(py // TILE_SIZE)) == _BLUE_MOUNTAINS_Z13_TILE

    def test_pixels_double_with_each_zoom_level(self):
        """Each zoom level doubles the global pixel plane."""
        px_z10, py_z10 = lonlat_to_pixel(-33.87, 151.21, 10)
        px_z11, py_z11 = lonlat_to_pixel(-33.87, 151.21, 11)

        assert px_z11 == pytest.approx(px_z10 * 2)
        assert py_z11 == pytest.approx(py_z10 * 2)


@pytest.mark.unit
class TestTrackBounds:
    """Test TrackBounds.from_coordinates."""

    def test_bounds_span_every_coordinate(self):
        """The bounding box covers the extremes of the coordinate list."""
        bounds = TrackBounds.from_coordinates(
            [(-33.70, 150.30), (-33.75, 150.40), (-33.68, 150.25)]
        )

        assert bounds.min_lat == pytest.approx(-33.75)
        assert bounds.max_lat == pytest.approx(-33.68)
        assert bounds.min_lon == pytest.approx(150.25)
        assert bounds.max_lon == pytest.approx(150.40)

    def test_empty_coordinates_are_rejected(self):
        """An empty track has no bounding box; the caller must not ask."""
        with pytest.raises(ValueError, match="at least one coordinate"):
            TrackBounds.from_coordinates([])


@pytest.mark.unit
class TestChooseZoom:
    """Test choose_zoom."""

    def test_zoom_fits_bounds_inside_the_tile_grid(self):
        """The chosen zoom's tile span never exceeds the allowed grid."""
        bounds = TrackBounds.from_coordinates([(-33.70, 150.30), (-33.78, 150.42)])

        zoom = choose_zoom(bounds, max_tiles_across=2)
        span = tile_span(bounds, zoom)

        assert span.tiles_across <= 2
        assert span.tiles_down <= 2

    def test_zoom_prefers_the_highest_level_that_fits(self):
        """One level in, the track would overflow the allowed grid."""
        bounds = TrackBounds.from_coordinates([(-33.70, 150.30), (-33.78, 150.42)])

        zoom = choose_zoom(bounds, max_tiles_across=2, max_zoom=18)
        assert zoom < 18  # otherwise this assertion proves nothing

        deeper = tile_span(bounds, zoom + 1)
        assert deeper.tiles_across > 2 or deeper.tiles_down > 2

    def test_single_point_track_clamps_to_max_zoom(self):
        """A degenerate bounding box fits at any zoom, so take the closest."""
        bounds = TrackBounds.from_coordinates([(-33.70, 150.30)])

        assert choose_zoom(bounds, max_tiles_across=2, max_zoom=17) == 17

    def test_world_spanning_track_clamps_to_min_zoom(self):
        """A track that fits at no zoom falls back to the widest view."""
        bounds = TrackBounds.from_coordinates([(-80.0, -179.0), (80.0, 179.0)])

        assert choose_zoom(bounds, max_tiles_across=2, min_zoom=1) == 1


@pytest.mark.unit
class TestTileSpan:
    """Test tile_span."""

    def test_tile_span_covers_every_coordinate(self):
        """Every coordinate's own tile lies inside the span."""
        coordinates = [(-33.70, 150.30), (-33.78, 150.42), (-33.74, 150.36)]
        bounds = TrackBounds.from_coordinates(coordinates)
        zoom = choose_zoom(bounds, max_tiles_across=2)

        span = tile_span(bounds, zoom)

        for lat, lon in coordinates:
            px, py = lonlat_to_pixel(lat, lon, zoom)
            assert span.x_min <= int(px // TILE_SIZE) <= span.x_max
            assert span.y_min <= int(py // TILE_SIZE) <= span.y_max

    def test_tile_span_enumerates_its_grid(self):
        """The span yields one coordinate per tile, row-major."""
        bounds = TrackBounds.from_coordinates([(-33.70, 150.30), (-33.78, 150.42)])
        zoom = choose_zoom(bounds, max_tiles_across=2)

        span = tile_span(bounds, zoom)
        tiles = list(span.tiles())

        assert len(tiles) == span.tiles_across * span.tiles_down
        assert all(tile.z == zoom for tile in tiles)
        assert tiles[0].x == span.x_min
        assert tiles[0].y == span.y_min

    def test_origin_pixel_is_the_top_left_tile_corner(self):
        """The span's origin anchors global pixels to the composed image."""
        bounds = TrackBounds.from_coordinates([(-33.70, 150.30), (-33.78, 150.42)])
        zoom = choose_zoom(bounds, max_tiles_across=2)

        span = tile_span(bounds, zoom)

        assert span.origin_pixel == (span.x_min * TILE_SIZE, span.y_min * TILE_SIZE)
