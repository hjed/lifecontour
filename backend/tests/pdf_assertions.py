"""Shared PDF-assertion helpers for logbook export tests.

Reading a real hyperlink annotation out of the rendered PDF — rather than
matching a URL-shaped string in the extracted text — is what proves a link is
actually clickable. The logbook renderer is exercised from unit, service-level
integration and API-level integration tests, so this lives in one place they
all import.
"""

import io

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
