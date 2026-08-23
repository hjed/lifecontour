"""HTTP glue for conditional requests (``ETag`` / ``If-Match``).

The tag itself and the matching rules live in :mod:`core_shared.etag`, shared
with the MCP surface; this module is only the part that is specific to HTTP —
reading the request header and stamping the response.

Controllers stay free of any decision: they hand whatever the client sent
straight to the service, which checks it inside the write's unit of work.
"""

from datetime import datetime

from core_shared.etag import parse_if_match, resource_etag
from fastapi import Request, Response


def get_if_match(request: Request) -> list[str] | None:
    """Return the request's ``If-Match`` precondition, or ``None`` if it sent none.

    Pass the result to the service's ``expected_etags``: ``None`` means write
    unconditionally, which is what every client did before conditional writes
    existed.
    """
    return parse_if_match(request.headers.get("If-Match"))


def set_etag(
    response: Response,
    resource_type: str,
    resource_id: int | str,
    updated_at: datetime | None,
) -> None:
    """Stamp the response with the resource's current entity-tag.

    A resource with no known ``updated_at`` has no version to advertise, and is
    left without the header rather than being given a tag that cannot be
    compared against anything.
    """
    etag = resource_etag(resource_type, resource_id, updated_at)
    if etag is not None:
        response.headers["ETag"] = etag
