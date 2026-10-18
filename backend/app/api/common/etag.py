"""HTTP glue for conditional requests (``ETag`` / ``If-Match``).

The tag itself and the matching rules live in :mod:`core_shared.etag`, shared
with the MCP surface; this module is only the part that is specific to HTTP —
reading the request header and stamping the response.

Controllers stay free of any decision: they hand whatever the client sent
straight to the service, which checks it inside the write's unit of work.
"""

from datetime import datetime
from typing import Any

from core_shared.etag import parse_if_match, resource_etag
from fastapi import Request, Response

from app.api.common.schemas import PreconditionFailedErrorResponse


def get_if_match(request: Request) -> list[str] | None:
    """Return the request's ``If-Match`` precondition, or ``None`` if it sent none.

    Pass the result to the service's ``expected_etags``: ``None`` means write
    unconditionally, which is what every client did before conditional writes
    existed.

    ``If-Match`` is a list-based field, so HTTP lets a sender split it across
    repeated header lines; ASGI keeps them separate. ``headers.get`` would
    return only the first, which would 412 a request whose matching tag was on
    a later line — the opposite of the any-tag-matches semantics. The lines are
    therefore rejoined, which is exactly how the field would have been sent as
    one line.
    """
    values = request.headers.getlist("If-Match")
    if not values:
        return None
    return parse_if_match(",".join(values))


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


def precondition_failed_responses(resource: str) -> dict[int | str, dict[str, Any]]:
    """The OpenAPI ``responses`` entry for a route that honours ``If-Match``.

    Args:
        resource: The aggregate the tag versions, as prose, e.g. ``"contact"``.
            A write to one of its rows is guarded by the aggregate's tag.
    """
    return {
        412: {
            "model": PreconditionFailedErrorResponse,
            "description": (
                f"The `If-Match` precondition named a version this {resource} "
                "has already moved on from — somebody else wrote to it since "
                "the caller read it. Nothing was written. The JSON:API error "
                "carries code `PRECONDITION_FAILED` and a `meta.current_etag` "
                "to retry with after re-reading and re-applying the change."
            ),
        },
    }
