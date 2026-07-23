"""Map-tile source port for the outdoor-logbook PDF (ITER16-004).

The outdoor-logbook PDF renders each activity's GPX track over a basemap
(Phase 6). Basemap tiles are fetched through this port so the concrete source
is swappable: OpenStreetMap standard tiles today, a keyed topo provider later,
without the renderer changing.

This module defines only the domain-facing contract (a value object, a typed
error, and the abstract source); the OSM implementation is an adapter under
``adapters/http``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TileCoordinate:
    """A single slippy-map tile address.

    Frozen so it is hashable and usable as a cache key. ``z`` is the zoom
    level; ``x``/``y`` are the tile column/row at that zoom.

    Attributes:
        z: Zoom level.
        x: Tile column (0 <= x < 2**z).
        y: Tile row (0 <= y < 2**z).
    """

    z: int
    x: int
    y: int


class TileFetchError(Exception):
    """Raised when a basemap tile cannot be fetched.

    A clean, typed failure so the renderer (Phase 6) can fall back to plotting
    the track on a plain background instead of failing the whole export.
    """


class TileSource(ABC):
    """Swappable source of basemap tiles for the logbook PDF.

    Implementations fetch a single tile by coordinate and expose the basemap's
    attribution text (rendered onto the map image). Batch-safety concerns
    (caching, throttling, User-Agent) are the implementation's responsibility.
    """

    @property
    @abstractmethod
    def attribution(self) -> str:
        """Attribution text to render on the map image (e.g. OSM credit)."""

    @abstractmethod
    async def fetch_tile(self, tile: TileCoordinate) -> bytes:
        """Return the raw image bytes for ``tile``.

        Raises:
            TileFetchError: If the tile cannot be retrieved.
        """
