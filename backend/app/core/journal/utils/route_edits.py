"""Build route entities from caller input, naming the field a refusal is about.

Shared by the REST converters and the MCP route tools, so both surfaces refuse
the same input on the same field.
"""

from core_shared.models import Route
from core_shared.models.journals import RouteValidationError


def route_error_field(error: ValueError) -> str:
    """The route field a ``Route`` entity validation error is about."""
    message = str(error).lower()
    if "gpx" in message:
        return "gpx_data"
    if "name" in message:
        return "name"
    return "route"


def build_new_route(
    *,
    journal_id: int,
    name: str,
    description: str | None,
    gpx_data: str | None,
) -> Route:
    """Build an unsaved route, validating it before anything is written.

    Blank ``gpx_data`` is stored as absent, so "has GPX" means there is a track.

    Raises:
        RouteValidationError: naming the field the entity refused.
    """
    try:
        return Route(
            journal_id=journal_id,
            name=name,
            description=description,
            gpx_data=gpx_data if gpx_data and gpx_data.strip() else None,
        )
    except ValueError as e:
        raise RouteValidationError(route_error_field(e), str(e)) from e
