"""Build and edit route entities, naming the field a refusal is about.

Shared by the REST converters, the MCP route tools and ``RouteService``, so
every surface refuses the same input on the same field and records the same
history for a change.
"""

from dataclasses import dataclass
from enum import Enum

from core_shared.models import Route
from core_shared.models.journals import RouteValidationError

#: ``{field: (old, new)}`` pairs, as published on ``RouteUpdated``.
ChangedFields = dict[str, tuple[str | None, str | None]]


class Unchanged(Enum):
    """Marks a ``RouteEdit`` field the caller did not ask to change."""

    UNCHANGED = "unchanged"


UNCHANGED = Unchanged.UNCHANGED


@dataclass(frozen=True)
class RouteEdit:
    """The route fields a caller asked to change.

    ``UNCHANGED`` keeps the current value. ``None`` is a real value: it clears
    the description or removes the GPX track.
    """

    name: str | Unchanged = UNCHANGED
    description: str | None | Unchanged = UNCHANGED
    gpx_data: str | None | Unchanged = UNCHANGED


def route_error_field(error: ValueError) -> str:
    """The route field a ``Route`` entity validation error is about."""
    message = str(error).lower()
    if "gpx" in message:
        return "gpx_data"
    if "name" in message:
        return "name"
    return "route"


def _resolve[T](requested: T | Unchanged, current: T) -> T:
    return current if isinstance(requested, Unchanged) else requested


def _stored_gpx(gpx_data: str | None) -> str | None:
    """Blank GPX is stored as absent, so "has GPX" means there is a track."""
    return gpx_data if gpx_data and gpx_data.strip() else None


def _gpx_presence(gpx_data: str | None) -> str | None:
    return "present" if _stored_gpx(gpx_data) else None


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


def apply_route_update(existing: Route, edit: RouteEdit) -> tuple[Route, ChangedFields]:
    """Apply an edit to a route and report what changed.

    Identity, parent journal and timestamps come from ``existing``, never the
    caller. GPX changes are recorded as presence (``"present"``/``None``) rather
    than content, because a track can be megabytes.

    Raises:
        RouteValidationError: naming the field the entity refused.
    """
    name = _resolve(edit.name, existing.name)
    description = _resolve(edit.description, existing.description)
    # GPX the edit does not touch is kept exactly as stored, so an unrelated
    # edit never rewrites it (not even blank GPX saved before normalisation).
    gpx_data = (
        existing.gpx_data
        if isinstance(edit.gpx_data, Unchanged)
        else _stored_gpx(edit.gpx_data)
    )
    try:
        updated = Route(
            id=existing.id,
            journal_id=existing.journal_id,
            name=name,
            description=description,
            gpx_data=gpx_data,
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
    # Blank and absent GPX are the same track, so moving between them is not
    # a change worth recording.
    if _stored_gpx(gpx_data) != _stored_gpx(existing.gpx_data):
        changed["gpx_data"] = (
            _gpx_presence(existing.gpx_data),
            _gpx_presence(gpx_data),
        )
    return updated, changed
