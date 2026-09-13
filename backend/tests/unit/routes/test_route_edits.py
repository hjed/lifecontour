"""Unit tests for the route edit helpers shared by the REST and MCP surfaces."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from core_shared.models import Route
from core_shared.models.journals import RouteValidationError

from app.core.journal.utils.route_edits import (
    RouteEdit,
    apply_route_update,
    build_new_route,
)

VALID_GPX = '<?xml version="1.0"?><gpx version="1.1" creator="test"></gpx>'


def _existing(
    *, name: str = "Trail", description: str | None = None, gpx_data: str | None = None
) -> Route:
    return Route(
        id=uuid4(),
        journal_id=1,
        name=name,
        description=description,
        gpx_data=gpx_data,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


@pytest.mark.unit
class TestApplyRouteUpdate:
    """``changed_fields`` pairs are published on ``RouteUpdated`` and projected
    under the parent journal as ``route:<id>:<field>`` history rows."""

    def test_an_empty_edit_keeps_every_field(self) -> None:
        existing = _existing(description="d", gpx_data=VALID_GPX)

        updated, changed = apply_route_update(existing, RouteEdit())

        assert (updated.name, updated.description, updated.gpx_data) == (
            "Trail",
            "d",
            VALID_GPX,
        )
        assert changed == {}

    def test_setting_the_current_values_changes_nothing(self) -> None:
        existing = _existing(description="d")

        _, changed = apply_route_update(
            existing, RouteEdit(name="Trail", description="d", gpx_data=None)
        )

        assert changed == {}

    def test_name_change_is_a_pair_and_other_fields_are_kept(self) -> None:
        existing = _existing(name="Old", description="kept", gpx_data=VALID_GPX)

        updated, changed = apply_route_update(existing, RouteEdit(name="New"))

        assert (updated.name, updated.description, updated.gpx_data) == (
            "New",
            "kept",
            VALID_GPX,
        )
        assert changed == {"name": ("Old", "New")}

    def test_description_change_is_a_pair(self) -> None:
        existing = _existing(description="old")

        _, changed = apply_route_update(existing, RouteEdit(description="new"))

        assert changed == {"description": ("old", "new")}

    def test_a_none_description_clears_it(self) -> None:
        existing = _existing(description="old")

        updated, changed = apply_route_update(existing, RouteEdit(description=None))

        assert updated.description is None
        assert changed == {"description": ("old", None)}

    def test_gpx_data_change_is_summarised_not_inlined(self) -> None:
        existing = _existing(gpx_data=None)

        updated, changed = apply_route_update(existing, RouteEdit(gpx_data=VALID_GPX))

        # GPX content is large, so the pair records presence rather than content.
        assert updated.gpx_data == VALID_GPX
        assert changed == {"gpx_data": (None, "present")}

    def test_blank_gpx_data_removes_the_track(self) -> None:
        existing = _existing(gpx_data=VALID_GPX)

        updated, changed = apply_route_update(existing, RouteEdit(gpx_data="  "))

        assert updated.gpx_data is None
        assert changed == {"gpx_data": ("present", None)}

    def test_keeps_identity_and_timestamps(self) -> None:
        existing = _existing()

        updated, _ = apply_route_update(existing, RouteEdit(name="New"))

        assert updated.id == existing.id
        assert updated.journal_id == existing.journal_id
        assert updated.created_at == existing.created_at
        assert updated.updated_at == existing.updated_at

    def test_invalid_gpx_names_the_gpx_data_field(self) -> None:
        with pytest.raises(RouteValidationError) as exc_info:
            apply_route_update(_existing(), RouteEdit(gpx_data="not xml"))

        assert exc_info.value.field == "gpx_data"


@pytest.mark.unit
class TestBuildNewRoute:
    def test_builds_an_unsaved_route(self) -> None:
        route = build_new_route(
            journal_id=7, name="Harbour Loop", description="d", gpx_data=VALID_GPX
        )

        assert route.id is None
        assert route.journal_id == 7
        assert route.name == "Harbour Loop"
        assert route.description == "d"
        assert route.gpx_data == VALID_GPX

    def test_blank_gpx_data_is_stored_as_absent(self) -> None:
        route = build_new_route(
            journal_id=7, name="Harbour Loop", description=None, gpx_data=""
        )

        assert route.gpx_data is None

    @pytest.mark.parametrize(
        ("gpx_data", "reason_fragment"),
        [
            ("this is not xml", "valid XML"),
            ("<kml><Document/></kml>", "<gpx> root"),
        ],
    )
    def test_invalid_gpx_names_the_gpx_data_field(
        self, gpx_data: str, reason_fragment: str
    ) -> None:
        with pytest.raises(RouteValidationError) as exc_info:
            build_new_route(
                journal_id=7, name="Harbour Loop", description=None, gpx_data=gpx_data
            )

        assert exc_info.value.field == "gpx_data"
        assert reason_fragment in exc_info.value.reason
        assert not exc_info.value.reason.startswith("gpx_data:")

    @pytest.mark.parametrize("name", ["", "   ", "x" * 201])
    def test_invalid_name_names_the_name_field(self, name: str) -> None:
        with pytest.raises(RouteValidationError) as exc_info:
            build_new_route(journal_id=7, name=name, description=None, gpx_data=None)

        assert exc_info.value.field == "name"
