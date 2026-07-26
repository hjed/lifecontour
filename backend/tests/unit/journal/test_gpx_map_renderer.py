"""Unit tests for the outdoor-logbook GPX map-image renderer (ITER16-004).

The renderer composes each entry's GPX track over basemap tiles into a PNG the
PDF embeds. The tile source is always a stub here, so these tests never touch
the live OSM tile servers, and the stub's tiles are a flat, unmistakable colour
so "the basemap was composited in" and "the plain-background fallback ran" are
distinguishable by pixel inspection rather than by trusting the code path.
"""

from __future__ import annotations

import datetime
import io
from collections.abc import Sequence
from typing import cast

import pytest
from core_shared.models.journals import EventDateRange, LogbookEntryData
from PIL import Image

from app.core.journal.models.tile_source import (
    TileCoordinate,
    TileFetchError,
    TileSource,
)
from app.core.journal.services.gpx_map_renderer import (
    FALLBACK_BACKGROUND_COLOUR,
    TRACK_COLOUR,
    GpxMapRenderer,
)
from app.core.journal.utils.slippy_map import TILE_SIZE

pytestmark = pytest.mark.unit

_TILE_COLOUR = (255, 0, 0)  # Unmistakable: no other ink in the image is red.
_ATTRIBUTION = "© OpenStreetMap contributors"

# A short Blue Mountains track, and a second one far enough away that including
# it must force a lower zoom level.
_TRACK_POINTS = [(-33.700, 150.300), (-33.705, 150.308), (-33.710, 150.315)]
_DISTANT_TRACK_POINTS = [(-33.980, 150.620), (-33.985, 150.628)]


def _gpx(points: list[tuple[float, float]]) -> str:
    """Build a minimal GPX document for the given ``(lat, lon)`` points."""
    return _gpx_raw([(str(lat), str(lon)) for lat, lon in points])


def _gpx_raw(points: list[tuple[str, str]]) -> str:
    """Build a GPX document from literal attribute text.

    Takes strings rather than floats so a document can carry values a float
    round-trip would never produce — ``nan``, ``inf`` — which is exactly what a
    corrupt or hand-edited track looks like.
    """
    trkpts = "".join(f'<trkpt lat="{lat}" lon="{lon}"/>' for lat, lon in points)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" '
        'xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>Track</name><trkseg>{trkpts}</trkseg></trk></gpx>"
    )


def _solid_tile_png(colour: tuple[int, int, int]) -> bytes:
    """Return a single-colour PNG tile."""
    buffer = io.BytesIO()
    Image.new("RGB", (TILE_SIZE, TILE_SIZE), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class _StubTileSource(TileSource):
    """A tile source that serves flat-colour tiles and records what was asked.

    ``error`` makes fetches fail, standing in for an offline or rate-limiting
    tile server; ``fail_after`` lets the first few tiles succeed so a *partly*
    fetched grid can be exercised, and ``tile_bytes`` overrides the served
    payload so an undecodable tile can be too.
    """

    def __init__(
        self,
        *,
        colour: tuple[int, int, int] = _TILE_COLOUR,
        attribution: str = _ATTRIBUTION,
        error: Exception | None = None,
        fail_after: int | None = None,
        tile_bytes: bytes | None = None,
    ) -> None:
        self.requested: list[TileCoordinate] = []
        self._colour = colour
        self._attribution = attribution
        self._error = error
        self._fail_after = fail_after
        self._tile_bytes = tile_bytes

    @property
    def attribution(self) -> str:
        return self._attribution

    async def fetch_tile(self, tile: TileCoordinate) -> bytes:
        self.requested.append(tile)
        if self._fail_after is not None and len(self.requested) > self._fail_after:
            raise TileFetchError("tile server gave up part-way through the grid")
        if self._error is not None:
            raise self._error
        if self._tile_bytes is not None:
            return self._tile_bytes
        return _solid_tile_png(self._colour)


def _entry(
    entry_id: int,
    *,
    gpx: list[str] | None = None,
    children: list[LogbookEntryData] | None = None,
) -> LogbookEntryData:
    """Build a minimal logbook entry, optionally carrying GPX routes."""
    moment = datetime.datetime(2026, 3, 12, tzinfo=datetime.UTC)
    return LogbookEntryData(
        id=entry_id,
        title=f"Entry {entry_id}",
        content="",
        event_date_range=EventDateRange(start=moment, end=moment),
        parent_id=None,
        children=children or [],
        journal_types=["BUSHWALKING"],
        route_gpx_data=gpx or [],
    )


def _colours(image: Image.Image) -> set[tuple[int, int, int]]:
    """Return the distinct RGB colours present in an image."""
    pixels = cast("Sequence[tuple[int, int, int]]", image.convert("RGB").getdata())
    return set(pixels)


def _open(png_bytes: bytes) -> Image.Image:
    """Decode PNG bytes, proving the renderer emitted a real image."""
    image = Image.open(io.BytesIO(png_bytes))
    image.load()
    assert image.format == "PNG"
    return image.convert("RGB")


def _attribution_band(image: Image.Image) -> Image.Image:
    """Crop the bottom-right corner where the attribution is drawn."""
    width, height = image.size
    return image.crop((width // 2, height - 20, width, height))


def _has_light_ink(image: Image.Image) -> bool:
    """Report whether the region holds the attribution's light backing plate.

    The plate is white blended over the red stub tiles, giving a warm pixel no
    other ink in the image can produce: the blue track and both markers are too
    dark in the red channel, the tiles have no green, and the plain fallback
    background is cool (its blue channel exceeds its red).
    """
    return any(r > 200 and g > 100 and r > b for r, g, b in _colours(image))


class TestMapImagePresence:
    """Which entries get a map image at all."""

    async def test_map_image_produced_for_entry_with_a_route(self) -> None:
        """An entry with a GPX route gets a decodable PNG map."""
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        assert list(images) == [1]
        assert _open(images[1]).size[0] > 0

    async def test_no_map_image_for_entry_without_a_route(self) -> None:
        """Entries with no GPX track omit the image entirely (spec §3.6)."""
        source = _StubTileSource()
        renderer = GpxMapRenderer(source)

        images = await renderer.build_map_images([_entry(1)])

        assert images == {}
        assert source.requested == []

    async def test_child_entry_gets_its_own_map_image(self) -> None:
        """The walk descends the hierarchy, not just the root entries."""
        child = _entry(2, gpx=[_gpx(_TRACK_POINTS)])
        parent = _entry(1, children=[child])
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images([parent])

        assert list(images) == [2]

    async def test_all_routes_of_an_entry_share_one_map_image(self) -> None:
        """Several routes compose into a single map fitted to all of them."""
        source = _StubTileSource()
        renderer = GpxMapRenderer(source)

        one_route = await renderer.build_map_images(
            [_entry(1, gpx=[_gpx(_TRACK_POINTS)])]
        )
        single_zoom = max(tile.z for tile in source.requested)

        source.requested.clear()
        both_routes = await renderer.build_map_images(
            [_entry(2, gpx=[_gpx(_TRACK_POINTS), _gpx(_DISTANT_TRACK_POINTS)])]
        )
        combined_zoom = max(tile.z for tile in source.requested)

        assert list(one_route) == [1]
        assert list(both_routes) == [2]
        # Fitting the far-away second route forces the view to zoom out; had it
        # been ignored, the zoom would have matched the single-route map.
        assert combined_zoom < single_zoom

    async def test_unparseable_gpx_is_skipped_without_failing(self) -> None:
        """Corrupt GPX degrades to no map rather than failing the export."""
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images([_entry(1, gpx=["not gpx at all"])])

        assert images == {}

    async def test_route_with_non_finite_latitude_is_skipped(self) -> None:
        """A NaN coordinate costs the entry its map, not the whole export.

        ``lat="nan"`` parses perfectly happily and survives the Mercator clamp,
        only to fail converting a pixel to a tile index — so without the guard
        this raises straight out of the export.
        """
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images(
            [_entry(1, gpx=[_gpx_raw([("nan", "150.300"), ("nan", "150.308")])])]
        )

        assert images == {}

    async def test_route_with_infinite_longitude_is_skipped(self) -> None:
        """An infinite coordinate fails inside gpxpy itself, as a bare ValueError."""
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images(
            [_entry(1, gpx=[_gpx_raw([("-33.700", "inf"), ("-33.705", "150.308")])])]
        )

        assert images == {}

    async def test_finite_points_of_a_partly_invalid_route_still_map(self) -> None:
        """One bad point does not discard the rest of the track."""
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images(
            [
                _entry(
                    1,
                    gpx=[
                        _gpx_raw(
                            [
                                ("nan", "150.300"),
                                ("-33.700", "150.300"),
                                ("-33.705", "150.308"),
                            ]
                        )
                    ],
                )
            ]
        )

        assert list(images) == [1]
        assert TRACK_COLOUR in _colours(_open(images[1]))

    async def test_route_with_no_track_points_produces_no_image(self) -> None:
        """A route carrying no track points has nothing to plot."""
        empty = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<gpx version="1.1" creator="test" '
            'xmlns="http://www.topografix.com/GPX/1/1">'
            "<trk><trkseg></trkseg></trk></gpx>"
        )
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images([_entry(1, gpx=[empty])])

        assert images == {}


class TestMapImageComposition:
    """What the composed image actually contains."""

    async def test_tiles_are_composited_into_the_image(self) -> None:
        """The basemap tiles land in the image, not just the track."""
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        assert _TILE_COLOUR in _colours(_open(images[1]))

    async def test_track_is_drawn_over_the_basemap(self) -> None:
        """The track ink is present on top of the tiles."""
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        assert TRACK_COLOUR in _colours(_open(images[1]))

    async def test_tile_fetches_bounded_by_the_grid(self) -> None:
        """Zoom is chosen so one map never costs more than its tile grid."""
        source = _StubTileSource()
        renderer = GpxMapRenderer(source, max_tiles_across=2)

        await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        assert 0 < len(source.requested) <= 4

    async def test_attribution_is_drawn_on_the_image(self) -> None:
        """The basemap's attribution is rendered onto the map (spec §3.6)."""
        renderer = GpxMapRenderer(_StubTileSource())

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        assert _has_light_ink(_attribution_band(_open(images[1])))

    async def test_no_attribution_band_when_source_reports_none(self) -> None:
        """Nothing is drawn when the source has no attribution to show.

        Pairs with the test above: without this, "ink in the bottom band" could
        be satisfied by any incidental drawing there.
        """
        renderer = GpxMapRenderer(_StubTileSource(attribution=""))

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        assert not _has_light_ink(_attribution_band(_open(images[1])))


class TestPlainBackgroundFallback:
    """Spec §3.6: unfetchable tiles must not fail the export."""

    async def test_fallback_plain_background_when_tile_fetch_fails(self) -> None:
        """The track is plotted on a plain background instead of tiles."""
        renderer = GpxMapRenderer(_StubTileSource(error=TileFetchError("offline")))

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        colours = _colours(_open(images[1]))
        assert _TILE_COLOUR not in colours
        assert FALLBACK_BACKGROUND_COLOUR in colours
        assert TRACK_COLOUR in colours

    async def test_partly_fetched_basemap_is_discarded(self) -> None:
        """A half-tiled basemap is thrown away rather than shown.

        Half a map reads as a rendering bug, so the whole basemap is dropped as
        soon as one tile is unusable — and fetching stops there rather than
        hammering a struggling tile server for the rest of the grid.
        """
        source = _StubTileSource(fail_after=1)
        renderer = GpxMapRenderer(source, max_tiles_across=2)

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        colours = _colours(_open(images[1]))
        assert _TILE_COLOUR not in colours
        assert FALLBACK_BACKGROUND_COLOUR in colours
        assert len(source.requested) == 2  # stopped at the first failure

    async def test_fallback_when_a_tile_cannot_be_decoded(self) -> None:
        """Bytes that are not a readable image degrade the same way."""
        renderer = GpxMapRenderer(_StubTileSource(tile_bytes=b"not-an-image"))

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        colours = _colours(_open(images[1]))
        assert FALLBACK_BACKGROUND_COLOUR in colours
        assert TRACK_COLOUR in colours

    async def test_fallback_when_a_tile_is_the_wrong_size(self) -> None:
        """A wrongly-sized tile is unusable, not merely ugly.

        The grid is laid out on ``TILE_SIZE`` offsets, so a substituted provider
        serving e.g. 512px retina tiles would leave the basemap misaligned
        against the track drawn over it — a map that is confidently wrong. It
        takes the same fallback as a tile that never arrived.
        """
        oversized = io.BytesIO()
        Image.new("RGB", (TILE_SIZE * 2, TILE_SIZE * 2), _TILE_COLOUR).save(
            oversized, format="PNG"
        )
        renderer = GpxMapRenderer(_StubTileSource(tile_bytes=oversized.getvalue()))

        images = await renderer.build_map_images([_entry(1, gpx=[_gpx(_TRACK_POINTS)])])

        colours = _colours(_open(images[1]))
        assert _TILE_COLOUR not in colours
        assert FALLBACK_BACKGROUND_COLOUR in colours
        assert TRACK_COLOUR in colours
