"""Shared PDF-assertion helpers for logbook export tests.

Reading real PDF structure out of the rendered document — a hyperlink
annotation, an embedded image XObject — rather than matching text that merely
looks right is what proves the feature is actually there: a URL-shaped string
in the text layer is not a clickable link, and an entry heading is not a map.
The logbook renderer is exercised from unit, service-level integration and
API-level integration tests, so these live in one place they all import.
"""

import io
import re

from pypdf import PdfReader


def external_link_uris(pdf_bytes: bytes) -> list[str]:
    """Collect every external hyperlink target, in document order.

    ReportLab renders ``<a href="https://…">`` as a ``/Link`` annotation whose
    ``/A`` action carries a ``/URI``. Internal (``#anchor``) links have no such
    action and are ignored.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    uris: list[str] = []
    for page in reader.pages:
        for annotation in page.get("/Annots") or []:
            obj = annotation.get_object()
            if obj.get("/Subtype") != "/Link":
                continue
            action = obj.get("/A")
            if action is None:
                continue
            uri = action.get_object().get("/URI")
            if uri is not None:
                uris.append(str(uri))
    return uris


def embedded_image_bytes(pdf_bytes: bytes) -> list[bytes]:
    """Collect the decoded bytes of every embedded raster image, in page order.

    ReportLab renders an ``Image`` flowable as an image XObject on the page, so
    this counts real pictures — the GPX track maps are currently the only raster
    content in the logbook PDF (the type icons are font glyphs, not images), and
    an entry with no map contributes nothing here.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [image.data for page in reader.pages for image in page.images]


def embedded_image_x_offsets(pdf_bytes: bytes) -> list[float]:
    """Collect the left edge, in points, of every drawn image, in page order.

    ReportLab places an image by translating the graphics state and then drawing
    an XObject, so the x of the enclosing ``cm`` matrix is where the image
    actually lands on the page. That is the only way to assert *alignment*:
    ``embedded_image_bytes`` proves a map exists, not that it sits where the
    entry's indentation says it should.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    offsets: list[float] = []
    for page in reader.pages:
        contents = page.get_contents()
        if contents is None:
            continue
        stream = contents.get_data().decode("latin-1")
        offsets.extend(
            float(x)
            for x in re.findall(
                r"1 0 0 1 ([\d.]+) [\d.-]+ cm\s+q\s+[\d.]+ 0 0 [\d.]+ 0 0 cm\s+/\S+ Do",
                stream,
            )
        )
    return offsets
