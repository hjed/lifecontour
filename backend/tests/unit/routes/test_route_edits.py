"""Unit tests for the route edit helpers shared by the REST and MCP surfaces."""

import pytest
from core_shared.models.journals import RouteValidationError

from app.core.journal.utils.route_edits import build_new_route

VALID_GPX = '<?xml version="1.0"?><gpx version="1.1" creator="test"></gpx>'


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
