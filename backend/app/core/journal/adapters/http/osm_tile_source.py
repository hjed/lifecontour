"""OpenStreetMap tile-source adapter for the outdoor-logbook PDF (ITER16-004).

Fetches OSM standard tiles for GPX map rendering. Export is a *batch* operation
that may render many tracks at once, so this adapter is batch-safe per OSM's
tile-usage policy:

* **On-disk cache** — tiles are keyed by ``z/x/y`` on disk, so a tile shared by
  several tracks or requested again at export time is fetched only once.
* **Throttle** — successive network fetches are paced to ≈2 tiles/second.
* **User-Agent** — every request carries a valid, identifying User-Agent.
* **Clean failure** — any HTTP/connection failure raises :class:`TileFetchError`
  and leaves the cache untouched, so the renderer can fall back to a plain
  background instead of failing the export.

It mirrors ``ImmichAlbumApiClient``: an injectable ``transport`` for tests, a
scheme check to guard against SSRF, and typed wrapping of ``httpx`` errors.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import structlog

from app.core.journal.models.tile_source import (
    TileCoordinate,
    TileFetchError,
    TileSource,
)

logger = structlog.get_logger(__name__)

_OSM_ATTRIBUTION = "© OpenStreetMap contributors"


class _TileThrottle:
    """Paces network fetches to at most ``tiles_per_second``.

    Records the last fetch time and sleeps just long enough before the next one
    so successive fetches are spaced by ``1 / tiles_per_second``. Cache hits do
    not call this, so only real network requests are throttled.
    """

    def __init__(self, tiles_per_second: float) -> None:
        self._interval = 1.0 / tiles_per_second if tiles_per_second > 0 else 0.0
        self._last: float | None = None

    async def wait(self) -> None:
        """Sleep if needed so the next fetch respects the minimum spacing."""
        if self._last is not None:
            elapsed = time.monotonic() - self._last
            remaining = self._interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last = time.monotonic()


class OsmTileSource(TileSource):
    """Batch-safe OpenStreetMap standard-tile source.

    Args:
        base_url: Tile server root, e.g. ``https://tile.openstreetmap.org``.
        user_agent: Identifying User-Agent sent on every request (OSM policy).
        cache_dir: Directory for the on-disk tile cache.
        tiles_per_second: Fetch throttle target (≈2 per OSM policy).
        transport: Optional ``httpx`` transport, injected by tests to stub HTTP.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        cache_dir: str | os.PathLike[str],
        tiles_per_second: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._cache_dir = Path(cache_dir)
        self._throttle = _TileThrottle(tiles_per_second)
        self._transport = transport
        self._timeout = timeout
        # Serialise network fetches so the throttle is honoured batch-wide even
        # if Phase 6 fetches tiles concurrently.
        self._lock = asyncio.Lock()

    @property
    def attribution(self) -> str:
        """OSM attribution, rendered onto the map image by the renderer."""
        return _OSM_ATTRIBUTION

    async def fetch_tile(self, tile: TileCoordinate) -> bytes:
        """Return the tile's PNG bytes, from cache or the tile server."""
        cache_path = self._cache_path(tile)

        # Cache hits skip both the lock and the throttle — they are cheap and
        # concurrency-safe (read-only).
        cached = self._read_cache(cache_path)
        if cached is not None:
            return cached

        # Guard against SSRF before any request is made.
        scheme = urlparse(self._base_url).scheme
        if scheme not in ("http", "https"):
            raise TileFetchError(f"Invalid tile server URL scheme: {scheme!r}")

        async with self._lock:
            # Another coroutine may have fetched this tile while we waited.
            cached = self._read_cache(cache_path)
            if cached is not None:
                return cached

            await self._throttle.wait()
            data = await self._fetch_from_network(tile)
            self._write_cache(cache_path, data)
            return data

    def _cache_path(self, tile: TileCoordinate) -> Path:
        return self._cache_dir / str(tile.z) / str(tile.x) / f"{tile.y}.png"

    @staticmethod
    def _read_cache(cache_path: Path) -> bytes | None:
        if cache_path.exists():
            return cache_path.read_bytes()
        return None

    @staticmethod
    def _write_cache(cache_path: Path, data: bytes) -> None:
        """Atomically write ``data`` to ``cache_path`` (temp file + rename)."""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as tmp_file:
                tmp_file.write(data)
            os.replace(tmp_name, cache_path)
        except BaseException:
            # Never leave a stray temp file behind on failure.
            Path(tmp_name).unlink(missing_ok=True)
            raise

    async def _fetch_from_network(self, tile: TileCoordinate) -> bytes:
        path = f"/{tile.z}/{tile.x}/{tile.y}.png"
        try:
            async with self._build_client() as client:
                response = await client.get(path)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            logger.warning(
                "OSM tile fetch failed",
                path=path,
                status=e.response.status_code,
            )
            raise TileFetchError(
                f"Tile server returned {e.response.status_code} for {path}"
            ) from e
        except httpx.RequestError as e:
            logger.warning("OSM tile request error", path=path, error=str(e))
            raise TileFetchError(f"Failed to fetch tile {path}: {e}") from e

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "image/png",
            },
            timeout=self._timeout,
            transport=self._transport,
        )
