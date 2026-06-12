"""Unit tests for route ``changed_fields`` computation (ITER12-002 Phase 2).

``RouteRequestConverter.from_update_request`` produces ``{field: (old, new)}``
pairs, which ``RouteService.update_route`` publishes on ``RouteUpdated`` and the
projection groups under the parent journal as ``route:<id>:<field>`` rows.
"""

from uuid import uuid4

from core_shared.models import Route

from app.api.routes.converters import RouteRequestConverter
from app.api.routes.schemas import RouteRequestAttributes, RouteUpdateData


def _existing(
    *, name: str = "Old", description: str | None = None, gpx_data: str | None = None
) -> Route:
    return Route(
        id=uuid4(),
        journal_id=1,
        name=name,
        description=description,
        gpx_data=gpx_data,
    )


def _update(
    existing: Route,
    *,
    name: str,
    description: str | None = None,
    gpx_data: str | None = None,
) -> RouteUpdateData:
    return RouteUpdateData(
        id=str(existing.id),
        attributes=RouteRequestAttributes(
            name=name, description=description, gpx_data=gpx_data
        ),
    )


class TestRouteChangedFields:
    def test_no_change_returns_empty(self) -> None:
        existing = _existing(name="Trail", description="d")
        _, changed = RouteRequestConverter.from_update_request(
            _update(existing, name="Trail", description="d"), existing
        )
        assert changed == {}

    def test_name_change_is_a_pair(self) -> None:
        existing = _existing(name="Old")
        _, changed = RouteRequestConverter.from_update_request(
            _update(existing, name="New"), existing
        )
        assert changed["name"] == ("Old", "New")

    def test_description_change_is_a_pair(self) -> None:
        existing = _existing(name="Trail", description="old")
        _, changed = RouteRequestConverter.from_update_request(
            _update(existing, name="Trail", description="new"), existing
        )
        assert changed["description"] == ("old", "new")

    def test_gpx_data_change_is_summarised_not_inlined(self) -> None:
        existing = _existing(name="Trail", gpx_data=None)
        _, changed = RouteRequestConverter.from_update_request(
            _update(existing, name="Trail", gpx_data="<gpx>...</gpx>"), existing
        )
        # GPX content is large, so the pair records presence rather than content.
        assert changed["gpx_data"] == (None, "present")
