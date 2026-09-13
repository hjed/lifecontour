"""Build route entities from caller input, naming the field a refusal is about.

Shared by the REST converters and the MCP route tools, so both surfaces refuse
the same input on the same field and record the same history for a change.
"""

from core_shared.models import Route
from core_shared.models.journals import RouteValidationError

#: ``{field: (old, new)}`` pairs, as published on ``RouteUpdated``.
ChangedFields = dict[str, tuple[str | None, str | None]]


def route_error_field(error: ValueError) -> str:
    """The route field a ``Route`` entity validation error is about."""
    message = str(error).lower()
    if "gpx" in message:
        return "gpx_data"
    if "name" in message:
        return "name"
    return "route"


def _stored_gpx(gpx_data: str | None) -> str | None:
    """Blank GPX is stored as absent, so "has GPX" means there is a track."""
    return gpx_data if gpx_data and gpx_data.strip() else None


def _gpx_presence(gpx_data: str | None) -> str | None:
    return "present" if gpx_data else None


def build_new_route(
    *,
    journal_id: int,
    name: str,
    description: str | None,
    gpx_data: str | None,
) -> Route:
    """Build an unsaved route, validating it before anything is written.

    Raises:
        RouteValidationError: naming the field the entity refused.
    """
    try:
        return Route(
            journal_id=journal_id,
            name=name,
            description=description,
            gpx_data=_stored_gpx(gpx_data),
        )
    except ValueError as e:
        raise RouteValidationError(route_error_field(e), str(e)) from e


def apply_route_update(
    existing: Route,
    *,
    name: str,
    description: str | None,
    gpx_data: str | None,
) -> tuple[Route, ChangedFields]:
    """Replace a route's editable fields and report what changed.

    Identity, parent journal and timestamps come from ``existing``, never the
    caller. GPX changes are recorded as presence (``"present"``/``None``) rather
    than content, because a track can be megabytes.

    Raises:
        RouteValidationError: naming the field the entity refused.
    """
    stored_gpx = _stored_gpx(gpx_data)
    try:
        updated = Route(
            id=existing.id,
            journal_id=existing.journal_id,
            name=name,
            description=description,
            gpx_data=stored_gpx,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )
    except ValueError as e:
        raise RouteValidationError(route_error_field(e), str(e)) from e

    changed: ChangedFields = {}
    if name != existing.name:
        changed["name"] = (existing.name, name)
    if description != existing.description:
        changed["description"] = (existing.description, description)
    if stored_gpx != existing.gpx_data:
        changed["gpx_data"] = (
            _gpx_presence(existing.gpx_data),
            _gpx_presence(stored_gpx),
        )
    return updated, changed
