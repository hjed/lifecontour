"""Slippy-map projection helpers for the outdoor-logbook PDF's GPX maps.

Pure Web-Mercator geometry — the same projection the tile server uses — so a
GPX track can be placed on a grid of fetched tiles:

* :func:`lonlat_to_pixel` projects a coordinate into the global pixel plane at
  a zoom level (``TILE_SIZE`` pixels per tile).
* :func:`choose_zoom` picks the closest zoom whose tile grid still contains the
  whole track, bounding how many tiles a single map costs to fetch.
* :func:`tile_span` enumerates that grid and anchors it back to global pixels.

All functions are pure and side-effect free; fetching tiles and compositing the
image live in the adapter and the map renderer respectively.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Final

from app.core.journal.models.tile_source import TileCoordinate

#: Edge length of a slippy-map tile in pixels (OSM standard tiles are 256px).
TILE_SIZE: Final = 256

# Web Mercator is undefined at the poles, so latitudes are clamped to the
# projection's usual limit rather than blowing up on a bad GPX point.
_MAX_LATITUDE: Final = 85.05112878

_DEFAULT_MIN_ZOOM: Final = 0
_DEFAULT_MAX_ZOOM: Final = 18


def lonlat_to_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Project a coordinate to global pixel coordinates at ``zoom``.

    The origin is the top-left of the world; x grows east, y grows south. The
    plane is ``TILE_SIZE * 2 ** zoom`` pixels square, so a tile's address is
    simply the pixel divided by :data:`TILE_SIZE`.

    Args:
        lat: Latitude in decimal degrees (clamped to the Mercator limit).
        lon: Longitude in decimal degrees.
        zoom: Zoom level.

    Returns:
        The ``(x, y)`` global pixel coordinates.
    """
    scale = TILE_SIZE * 2**zoom
    clamped_lat = max(min(lat, _MAX_LATITUDE), -_MAX_LATITUDE)
    clamped_lon = max(min(lon, 180.0), -180.0)

    x = (clamped_lon + 180.0) / 360.0 * scale
    y = (1.0 - math.asinh(math.tan(math.radians(clamped_lat))) / math.pi) / 2.0 * scale
    return x, y


@dataclass(frozen=True)
class TrackBounds:
    """The latitude/longitude bounding box of one or more GPX tracks."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    @classmethod
    def from_coordinates(
        cls, coordinates: Iterable[tuple[float, float]]
    ) -> TrackBounds:
        """Build the bounding box covering every ``(lat, lon)`` given.

        Raises:
            ValueError: If ``coordinates`` is empty — an empty track has no
                bounding box, and silently inventing one would place a map
                somewhere arbitrary.
        """
        latitudes: list[float] = []
        longitudes: list[float] = []
        for lat, lon in coordinates:
            latitudes.append(lat)
            longitudes.append(lon)

        if not latitudes:
            raise ValueError("Bounds need at least one coordinate")

        return cls(
            min_lat=min(latitudes),
            max_lat=max(latitudes),
            min_lon=min(longitudes),
            max_lon=max(longitudes),
        )


@dataclass(frozen=True)
class TileSpan:
    """The inclusive rectangle of tiles covering a track at one zoom level."""

    zoom: int
    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def tiles_across(self) -> int:
        """Number of tile columns in the span."""
        return self.x_max - self.x_min + 1

    @property
    def tiles_down(self) -> int:
        """Number of tile rows in the span."""
        return self.y_max - self.y_min + 1

    @property
    def origin_pixel(self) -> tuple[int, int]:
        """Global pixel coordinates of the span's top-left corner.

        Subtracting this from a projected coordinate converts it into a pixel
        position inside the composed image.
        """
        return self.x_min * TILE_SIZE, self.y_min * TILE_SIZE

    def tiles(self) -> Iterator[TileCoordinate]:
        """Yield every tile in the span, row-major from the top-left."""
        for y in range(self.y_min, self.y_max + 1):
            for x in range(self.x_min, self.x_max + 1):
                yield TileCoordinate(z=self.zoom, x=x, y=y)


def tile_span(bounds: TrackBounds, zoom: int) -> TileSpan:
    """Return the tiles covering ``bounds`` at ``zoom``."""
    west_px, north_px = lonlat_to_pixel(bounds.max_lat, bounds.min_lon, zoom)
    east_px, south_px = lonlat_to_pixel(bounds.min_lat, bounds.max_lon, zoom)

    last_tile = 2**zoom - 1
    return TileSpan(
        zoom=zoom,
        x_min=_tile_index(west_px, last_tile),
        y_min=_tile_index(north_px, last_tile),
        x_max=_tile_index(east_px, last_tile),
        y_max=_tile_index(south_px, last_tile),
    )


def choose_zoom(
    bounds: TrackBounds,
    *,
    max_tiles_across: int,
    min_zoom: int = _DEFAULT_MIN_ZOOM,
    max_zoom: int = _DEFAULT_MAX_ZOOM,
) -> int:
    """Return the closest zoom whose tile grid still contains ``bounds``.

    Scans from ``max_zoom`` downwards and returns the first zoom whose span
    fits within a ``max_tiles_across`` × ``max_tiles_across`` grid, so the
    number of tiles a map costs is bounded regardless of track length. A track
    too large to fit at any level falls back to ``min_zoom``.
    """
    for zoom in range(max_zoom, min_zoom, -1):
        span = tile_span(bounds, zoom)
        if (
            span.tiles_across <= max_tiles_across
            and span.tiles_down <= max_tiles_across
        ):
            return zoom
    return min_zoom


def _tile_index(pixel: float, last_tile: int) -> int:
    """Convert a global pixel coordinate to a tile index inside the plane."""
    return max(0, min(int(pixel // TILE_SIZE), last_tile))
