"""GPX map-image renderer for the outdoor-logbook PDF (ITER16-004).

Turns each entry's GPX routes into a single PNG the PDF embeds: the track drawn
over basemap tiles fetched through the swappable :class:`TileSource`, cropped to
the track's bounding box plus padding, with the basemap's attribution drawn onto
the image.

Two properties matter more than fidelity:

* **The export never fails because of a map.** If a tile cannot be fetched (or
  cannot be decoded), the track is plotted on a plain background instead; if a
  route's GPX cannot be parsed, that route is skipped. Both are logged.
* **Tile fetching stays bounded.** The zoom level is chosen as the closest one
  whose tile grid still contains the whole track, so a map costs at most
  ``max_tiles_across ** 2`` tiles no matter how long the track is. The adapter's
  cache and throttle then keep a batch export inside OSM's usage policy.

This is a separate service from ``LogbookPdfRenderer`` because composing the
image is asynchronous I/O while the PDF renderer is synchronous: images are
built first and handed to ``render(data, map_images=…)``.
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterator, Sequence
from typing import Final

import structlog
from core_shared.models.journals import GPXParsingError, LogbookEntryData
from PIL import Image, ImageDraw, ImageFont

from app.core.journal.models.tile_source import TileFetchError, TileSource
from app.core.journal.services.logbook_pdf_renderer import resolve_glyph_font_path
from app.core.journal.utils.gpx_parser import parse_gpx_track
from app.core.journal.utils.slippy_map import (
    TILE_SIZE,
    TileSpan,
    TrackBounds,
    choose_zoom,
    lonlat_to_pixel,
    tile_span,
)

logger = structlog.get_logger(__name__)

#: Track ink — the PDF's own accent colour (``#2b6cb0``). The in-app map's
#: colours come from theme CSS tokens, which have no meaning in a PDF.
TRACK_COLOUR: Final = (43, 108, 176)

#: The plain background the track is plotted on when tiles are unavailable.
FALLBACK_BACKGROUND_COLOUR: Final = (237, 242, 247)  # Slate-100

_START_MARKER_COLOUR: Final = (47, 133, 90)  # Green-600
_END_MARKER_COLOUR: Final = (197, 48, 48)  # Red-600
_TRACK_WIDTH: Final = 3
_MARKER_RADIUS: Final = 4

# Padding around the track's bounding box, and the smallest map we will emit —
# a very short track should still get a legible amount of surrounding context.
_PADDING_PX: Final = 24
_MIN_IMAGE_PX: Final = 192

# Zoom bounds: 17 is close enough to read a single gully, and 1 keeps a
# continent-spanning track on a recognisable world view.
_MIN_ZOOM: Final = 1
_MAX_ZOOM: Final = 17

_ATTRIBUTION_FONT_SIZE: Final = 10
_ATTRIBUTION_PLATE_COLOUR: Final = (255, 255, 255, 205)
_ATTRIBUTION_TEXT_COLOUR: Final = (45, 55, 72)  # Slate-700
_ATTRIBUTION_INSET: Final = 3

_PixelTrack = list[tuple[float, float]]


class GpxMapRenderer:
    """Composes per-entry GPX map images for the outdoor-logbook PDF.

    Args:
        tile_source: Swappable basemap source; its cache and throttle make batch
            fetching policy-compliant.
        max_tiles_across: Upper bound on the tile grid a single map may use, and
            therefore on how many tiles it costs to fetch.
        attribution_font_path: Font for the attribution text. Defaults to the
            same DejaVu-class system font the PDF's type glyphs use, falling
            back to Pillow's built-in bitmap font when none is installed.
    """

    def __init__(
        self,
        tile_source: TileSource,
        *,
        max_tiles_across: int = 2,
        attribution_font_path: str | None = None,
    ) -> None:
        self._tile_source = tile_source
        self._max_tiles_across = max_tiles_across
        self._attribution_font_path = attribution_font_path or resolve_glyph_font_path()

    async def build_map_images(
        self, entries: Sequence[LogbookEntryData]
    ) -> dict[int, bytes]:
        """Return PNG map images keyed by journal id.

        Walks the whole entry hierarchy, so child activities get their own maps.
        Entries with no route — or whose every route fails to parse — are absent
        from the result, which is how the PDF knows to omit the image.
        """
        images: dict[int, bytes] = {}
        for entry in _walk(entries):
            if entry.id is None or not entry.route_gpx_data:
                continue
            tracks = self._parse_tracks(entry)
            if not tracks:
                continue
            images[entry.id] = await self._render_map(tracks)
        return images

    def _parse_tracks(self, entry: LogbookEntryData) -> list[list[tuple[float, float]]]:
        """Parse the entry's routes into ``(lat, lon)`` tracks, skipping bad ones.

        One track per route: ``parse_gpx_track`` already concatenates the
        segments within a route, so a route is drawn as a single polyline.

        Non-finite coordinates are dropped rather than projected. A GPX carrying
        ``lat="nan"`` parses perfectly happily, and NaN survives the Mercator
        clamp only to blow up converting a pixel to a tile index; ``inf`` fails
        even earlier, inside gpxpy's own distance maths. Both surface as a plain
        ``ValueError``, which is why one is caught alongside ``GPXParsingError``
        — an unusable track must cost the entry its map, never the whole export.
        """
        tracks: list[list[tuple[float, float]]] = []
        for gpx_xml in entry.route_gpx_data:
            try:
                parsed = parse_gpx_track(gpx_xml)
            except (GPXParsingError, ValueError) as e:
                logger.warning(
                    "logbook_map_route_unparseable",
                    message="Skipping a route whose GPX could not be parsed",
                    journal_id=entry.id,
                    error=str(e),
                )
                continue
            points = [
                (c.latitude, c.longitude)
                for c in parsed.coordinates
                if math.isfinite(c.latitude) and math.isfinite(c.longitude)
            ]
            if len(points) < len(parsed.coordinates):
                logger.warning(
                    "logbook_map_route_has_invalid_points",
                    message="Dropped non-finite coordinates from a route",
                    journal_id=entry.id,
                    dropped=len(parsed.coordinates) - len(points),
                )
            if points:
                tracks.append(points)
        return tracks

    async def _render_map(self, tracks: list[list[tuple[float, float]]]) -> bytes:
        """Compose one map image covering every track given."""
        bounds = TrackBounds.from_coordinates(
            point for track in tracks for point in track
        )
        zoom = choose_zoom(
            bounds,
            max_tiles_across=self._max_tiles_across,
            min_zoom=_MIN_ZOOM,
            max_zoom=_MAX_ZOOM,
        )
        span = tile_span(bounds, zoom)

        canvas = await self._compose_basemap(span)
        pixel_tracks = _to_pixel_tracks(tracks, span)

        _draw_tracks(canvas, pixel_tracks)
        image = canvas.crop(_crop_box(pixel_tracks, canvas.size))
        self._draw_attribution(image)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    async def _compose_basemap(self, span: TileSpan) -> Image.Image:
        """Fetch and stitch the span's tiles, or return a plain background.

        A single unusable tile discards the whole basemap: half a map reads as a
        rendering bug, whereas the plain background is an honest "no basemap
        available" the spec asks for. Fetching stops at the first failure so a
        struggling tile server is not hammered for the rest of the grid.
        """
        size = (span.tiles_across * TILE_SIZE, span.tiles_down * TILE_SIZE)
        canvas = Image.new("RGB", size, FALLBACK_BACKGROUND_COLOUR)
        origin_x, origin_y = span.origin_pixel

        for tile in span.tiles():
            try:
                tile_bytes = await self._tile_source.fetch_tile(tile)
                with Image.open(io.BytesIO(tile_bytes)) as tile_image:
                    # A tile of the wrong size is worse than no tile: the grid is
                    # laid out on TILE_SIZE offsets, so e.g. a 512px retina tile
                    # from a substituted provider would leave the basemap
                    # misaligned against the track it is supposed to sit under.
                    if tile_image.size != (TILE_SIZE, TILE_SIZE):
                        raise ValueError(
                            f"Tile is {tile_image.size}, expected "
                            f"{(TILE_SIZE, TILE_SIZE)}"
                        )
                    canvas.paste(
                        tile_image.convert("RGB"),
                        (tile.x * TILE_SIZE - origin_x, tile.y * TILE_SIZE - origin_y),
                    )
            except (TileFetchError, OSError, ValueError) as e:
                logger.warning(
                    "logbook_map_basemap_unavailable",
                    message=(
                        "Basemap tiles unavailable; plotting the track on a "
                        "plain background"
                    ),
                    zoom=tile.z,
                    error=str(e),
                )
                return Image.new("RGB", size, FALLBACK_BACKGROUND_COLOUR)

        return canvas

    def _draw_attribution(self, image: Image.Image) -> None:
        """Draw the basemap's attribution into the image's bottom-right corner."""
        text = self._tile_source.attribution
        if not text:
            return

        draw = ImageDraw.Draw(image, "RGBA")
        font = self._attribution_font()
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        text_width = right - left
        text_height = bottom - top

        x = image.width - text_width - 2 * _ATTRIBUTION_INSET
        y = image.height - text_height - 2 * _ATTRIBUTION_INSET

        # A light plate keeps the credit legible over dark map detail.
        draw.rectangle(
            (x - _ATTRIBUTION_INSET, y - _ATTRIBUTION_INSET, image.width, image.height),
            fill=_ATTRIBUTION_PLATE_COLOUR,
        )
        draw.text((x - left, y - top), text, fill=_ATTRIBUTION_TEXT_COLOUR, font=font)

    def _attribution_font(self) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
        """Return the attribution font, degrading to the built-in bitmap font."""
        if self._attribution_font_path is not None:
            try:
                return ImageFont.truetype(
                    self._attribution_font_path, _ATTRIBUTION_FONT_SIZE
                )
            except OSError as e:
                logger.warning(
                    "logbook_map_attribution_font_unusable",
                    message="Falling back to the built-in font for map attribution",
                    font_path=self._attribution_font_path,
                    error=str(e),
                )
        return ImageFont.load_default()


def _walk(entries: Sequence[LogbookEntryData]) -> Iterator[LogbookEntryData]:
    """Yield every entry in the hierarchy, parents before children."""
    for entry in entries:
        yield entry
        yield from _walk(entry.children)


def _to_pixel_tracks(
    tracks: list[list[tuple[float, float]]], span: TileSpan
) -> list[_PixelTrack]:
    """Project tracks into pixel positions inside the composed basemap."""
    origin_x, origin_y = span.origin_pixel
    pixel_tracks: list[_PixelTrack] = []
    for track in tracks:
        projected = [lonlat_to_pixel(lat, lon, span.zoom) for lat, lon in track]
        pixel_tracks.append([(px - origin_x, py - origin_y) for px, py in projected])
    return pixel_tracks


def _draw_tracks(canvas: Image.Image, pixel_tracks: list[_PixelTrack]) -> None:
    """Draw each track as a polyline with start and end markers."""
    draw = ImageDraw.Draw(canvas)
    for points in pixel_tracks:
        if len(points) > 1:
            draw.line(points, fill=TRACK_COLOUR, width=_TRACK_WIDTH, joint="curve")
        _draw_marker(draw, points[0], _START_MARKER_COLOUR)
        _draw_marker(draw, points[-1], _END_MARKER_COLOUR)


def _draw_marker(
    draw: ImageDraw.ImageDraw, point: tuple[float, float], colour: tuple[int, int, int]
) -> None:
    """Draw a single track endpoint marker."""
    x, y = point
    draw.ellipse(
        (
            x - _MARKER_RADIUS,
            y - _MARKER_RADIUS,
            x + _MARKER_RADIUS,
            y + _MARKER_RADIUS,
        ),
        fill=colour,
        outline=TRACK_COLOUR,
        width=1,
    )


def _crop_box(
    pixel_tracks: list[_PixelTrack], canvas_size: tuple[int, int]
) -> tuple[int, int, int, int]:
    """Return the padded bounding box of the tracks, clamped to the canvas."""
    xs = [x for track in pixel_tracks for x, _y in track]
    ys = [y for track in pixel_tracks for _x, y in track]

    width, height = canvas_size
    left, right = _padded_extent(min(xs), max(xs), width)
    top, bottom = _padded_extent(min(ys), max(ys), height)
    return left, top, right, bottom


def _padded_extent(low: float, high: float, limit: int) -> tuple[int, int]:
    """Pad one axis of the track's extent, keeping it inside ``[0, limit]``."""
    low -= _PADDING_PX
    high += _PADDING_PX

    # Grow a very short extent around its centre so the map stays legible.
    shortfall = min(_MIN_IMAGE_PX, limit) - (high - low)
    if shortfall > 0:
        low -= shortfall / 2
        high += shortfall / 2

    # Slide, rather than shrink, an extent that overhangs an edge.
    if low < 0:
        high -= low
        low = 0
    if high > limit:
        low -= high - limit
        high = limit

    return max(0, int(low)), min(limit, int(high))
