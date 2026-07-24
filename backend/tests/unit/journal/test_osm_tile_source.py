"""Unit tests for the OSM map-tile source adapter (ITER16-004 Phase 5).

The adapter fetches OpenStreetMap standard tiles for the outdoor-logbook PDF's
GPX maps. Because export is a batch operation, the adapter must be batch-safe:
an on-disk tile cache (deduping tiles shared across entries/zooms), a polite
≈2 tiles/second throttle, a valid User-Agent, and a clean typed failure mode.

All HTTP is stubbed via ``httpx.MockTransport`` — these tests never touch the
live OSM tile servers. The on-disk cache is exercised against a real ``tmp_path``
directory, and the throttle is verified by patching ``asyncio.sleep`` so no real
time passes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.journal.adapters.http.osm_tile_source import OsmTileSource
from app.core.journal.models.tile_source import (
    TileCoordinate,
    TileFetchError,
    TileSource,
)

pytestmark = pytest.mark.unit

_BASE_URL = "https://tile.openstreetmap.org"
_USER_AGENT = "PersonalManagementSystem/1.0 (outdoor-logbook-pdf)"
_TILE_BYTES = b"\x89PNG\r\n\x1a\n-fake-tile-bytes"
_TILE = TileCoordinate(z=5, x=15, y=10)


class _RecordingHandler:
    """Records requests and serves a scripted response (or raises)."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = _TILE_BYTES,
        raise_error: Exception | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._status_code = status_code
        self._content = content
        self._raise_error = raise_error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._raise_error is not None:
            raise self._raise_error
        # Bind the request so response.raise_for_status() raises a proper
        # HTTPStatusError (not a RuntimeError) across httpx versions.
        return httpx.Response(self._status_code, content=self._content, request=request)


def _make_source(
    cache_dir: Path,
    handler: _RecordingHandler,
    *,
    tiles_per_second: float = 2.0,
    base_url: str = _BASE_URL,
    monotonic: Callable[[], float] = time.monotonic,
) -> OsmTileSource:
    return OsmTileSource(
        base_url=base_url,
        user_agent=_USER_AGENT,
        cache_dir=cache_dir,
        tiles_per_second=tiles_per_second,
        transport=httpx.MockTransport(handler),
        monotonic=monotonic,
    )


class _StepClock:
    """Deterministic monotonic clock returning scripted values in order.

    Repeats the final value if called more times than scripted, so the test
    can't break if the throttle reads the clock an extra time.
    """

    def __init__(self, values: list[float]) -> None:
        self._values = values
        self._index = 0

    def __call__(self) -> float:
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return value


def _cached_tiles(cache_dir: Path) -> list[bytes]:
    """Sync helper: the bytes of every cached ``*.png`` under ``cache_dir``.

    Kept sync (not called via ``pathlib`` inside the async tests) to satisfy
    the ASYNC240 lint that forbids blocking pathlib calls in async functions.
    """
    return [path.read_bytes() for path in sorted(cache_dir.rglob("*.png"))]


class TestOsmTileSourceContract:
    """The adapter satisfies the swappable ``TileSource`` port."""

    def test_is_a_tile_source(self, tmp_path: Path) -> None:
        source = _make_source(tmp_path, _RecordingHandler())
        assert isinstance(source, TileSource)

    def test_attribution_exposed(self, tmp_path: Path) -> None:
        # Phase 6 draws this onto the map image, so the adapter must expose it.
        source = _make_source(tmp_path, _RecordingHandler())
        assert "OpenStreetMap" in source.attribution


class TestOsmTileSourceFetch:
    """Fetching, URL shape, and User-Agent."""

    async def test_fetch_tile_returns_served_bytes(self, tmp_path: Path) -> None:
        source = _make_source(tmp_path, _RecordingHandler())
        assert await source.fetch_tile(_TILE) == _TILE_BYTES

    async def test_fetch_tile_requests_osm_zxy_url(self, tmp_path: Path) -> None:
        handler = _RecordingHandler()
        source = _make_source(tmp_path, handler)

        await source.fetch_tile(_TILE)

        assert len(handler.requests) == 1
        assert str(handler.requests[0].url) == f"{_BASE_URL}/5/15/10.png"

    async def test_user_agent_header_applied(self, tmp_path: Path) -> None:
        handler = _RecordingHandler()
        source = _make_source(tmp_path, handler)

        await source.fetch_tile(_TILE)

        assert handler.requests[0].headers["user-agent"] == _USER_AGENT


class TestOsmTileSourceCache:
    """On-disk cache dedups tiles across entries/zooms."""

    async def test_cache_hit_avoids_second_fetch(self, tmp_path: Path) -> None:
        handler = _RecordingHandler()
        source = _make_source(tmp_path, handler)

        first = await source.fetch_tile(_TILE)
        second = await source.fetch_tile(_TILE)

        # The second fetch is served from disk: no additional network request.
        assert len(handler.requests) == 1
        assert first == second == _TILE_BYTES

    async def test_cache_write_is_atomic_bytes_roundtrip(self, tmp_path: Path) -> None:
        source = _make_source(tmp_path, _RecordingHandler())

        await source.fetch_tile(_TILE)

        assert _cached_tiles(tmp_path) == [_TILE_BYTES]

    async def test_cache_hit_does_not_throttle(self, tmp_path: Path) -> None:
        source = _make_source(tmp_path, _RecordingHandler())

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await source.fetch_tile(_TILE)  # miss: first fetch never sleeps
            await source.fetch_tile(_TILE)  # hit: must skip the throttle

        mock_sleep.assert_not_called()

    async def test_cache_write_failure_still_returns_bytes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A failed cache write (disk full, read-only) must not discard a tile
        # we already fetched — return the bytes best-effort.
        source = _make_source(tmp_path, _RecordingHandler())

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(source, "_write_cache", _boom)

        assert await source.fetch_tile(_TILE) == _TILE_BYTES


class TestOsmTileSourceThrottle:
    """The ≈2 tiles/second throttle paces successive network fetches."""

    async def test_throttle_paces_successive_fetches(self, tmp_path: Path) -> None:
        handler = _RecordingHandler()
        # Deterministic clock (not real wall-clock, so a slow CI runner can't
        # make this flaky): the two fetches read 100.0 then 100.1 — 0.1s apart,
        # inside the 0.5s window — so the throttle must sleep for 0.4s.
        clock = _StepClock([100.0, 100.1])
        source = _make_source(tmp_path, handler, tiles_per_second=2.0, monotonic=clock)
        other_tile = TileCoordinate(z=5, x=16, y=10)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await source.fetch_tile(_TILE)  # first fetch: no wait
            await source.fetch_tile(other_tile)  # second fetch: paced

        assert len(handler.requests) == 2
        mock_sleep.assert_awaited_once()
        await_args = mock_sleep.await_args
        assert await_args is not None
        (delay,) = await_args.args
        # 1 / 2 tiles per second = 0.5s spacing, minus the 0.1s already elapsed.
        assert delay == pytest.approx(0.4)


class TestOsmTileSourceFailure:
    """Failures surface cleanly as ``TileFetchError`` and never poison the cache."""

    async def test_http_error_raises_tile_fetch_error(self, tmp_path: Path) -> None:
        source = _make_source(tmp_path, _RecordingHandler(status_code=500))

        with pytest.raises(TileFetchError):
            await source.fetch_tile(_TILE)

    async def test_connection_error_raises_tile_fetch_error(
        self, tmp_path: Path
    ) -> None:
        handler = _RecordingHandler(
            raise_error=httpx.ConnectError("connection refused")
        )
        source = _make_source(tmp_path, handler)

        with pytest.raises(TileFetchError):
            await source.fetch_tile(_TILE)

    async def test_failure_writes_no_cache(self, tmp_path: Path) -> None:
        source = _make_source(tmp_path, _RecordingHandler(status_code=500))

        with pytest.raises(TileFetchError):
            await source.fetch_tile(_TILE)

        assert _cached_tiles(tmp_path) == []

    async def test_invalid_scheme_rejected_without_network(
        self, tmp_path: Path
    ) -> None:
        # SSRF guard: a non-http(s) tile URL must fail before any request.
        handler = _RecordingHandler()
        source = _make_source(tmp_path, handler, base_url="ftp://tiles.example")

        with pytest.raises(TileFetchError):
            await source.fetch_tile(_TILE)

        assert handler.requests == []
