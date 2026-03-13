"""Unit tests for Route entity."""

from datetime import datetime
from uuid import uuid4

import pytest
from core_shared.models.route import Route


@pytest.mark.unit
class TestRoute:
    """Test Route entity."""

    def test_create_route_minimal(self):
        """Test creating route with minimal required fields."""
        route = Route(
            journal_id=1,
            name="Mount Kosciuszko Summit Track",
        )
        assert route.journal_id == 1
        assert route.name == "Mount Kosciuszko Summit Track"
        assert route.id is None
        assert route.description is None
        assert route.gpx_data is None
        assert route.created_at is None
        assert route.updated_at is None

    def test_create_route_with_all_fields(self):
        """Test creating route with all fields populated."""
        route_id = uuid4()
        now = datetime.now()
        gpx_data = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <name>Test Track</name>
    <trkseg>
      <trkpt lat="-36.4567" lon="148.2634">
        <ele>2228</ele>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""

        route = Route(
            id=route_id,
            journal_id=1,
            name="Mount Kosciuszko Summit Track",
            description="Main walking track to the summit of Australia's highest mountain",
            gpx_data=gpx_data,
            created_at=now,
            updated_at=now,
        )

        assert route.id == route_id
        assert route.journal_id == 1
        assert route.name == "Mount Kosciuszko Summit Track"
        assert (
            route.description
            == "Main walking track to the summit of Australia's highest mountain"
        )
        assert route.gpx_data == gpx_data
        assert route.created_at == now
        assert route.updated_at == now

    def test_route_name_required(self):
        """Test that route name is required."""
        with pytest.raises(ValueError, match="Route name is required"):
            Route(journal_id=1, name="")

    def test_route_name_max_length(self):
        """Test that route name cannot exceed 200 characters."""
        long_name = "A" * 201
        with pytest.raises(ValueError, match="Route name cannot exceed 200 characters"):
            Route(journal_id=1, name=long_name)

    def test_route_journal_id_required(self):
        """Test that user_id is required."""
        with pytest.raises(ValueError, match="Journal ID must be a positive integer"):
            Route(journal_id=0, name="Test Route")

    def test_route_journal_id_validation(self):
        """Test that user_id cannot exceed 50 characters."""
        with pytest.raises(ValueError, match="Journal ID must be a positive integer"):
            Route(journal_id=-1, name="Test Route")

    def test_route_gpx_data_optional(self):
        """Test that GPX data is optional."""
        route = Route(
            journal_id=1,
            name="Test Route",
            gpx_data=None,
        )
        assert route.gpx_data is None

    def test_route_gpx_validation_valid_xml(self):
        """Test that valid GPX XML is accepted."""
        valid_gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <name>Test Track</name>
  </trk>
</gpx>"""
        route = Route(
            journal_id=1,
            name="Test Route",
            gpx_data=valid_gpx,
        )
        assert route.gpx_data == valid_gpx

    def test_route_gpx_validation_invalid_xml(self):
        """Test that invalid GPX XML raises error."""
        invalid_gpx = "This is not XML"
        with pytest.raises(ValueError, match="GPX data must be valid XML"):
            Route(
                journal_id=1,
                name="Test Route",
                gpx_data=invalid_gpx,
            )

    def test_route_gpx_validation_missing_gpx_root(self):
        """Test that XML without GPX root element raises error."""
        invalid_gpx = """<?xml version="1.0" encoding="UTF-8"?>
<root>
  <data>Not a GPX file</data>
</root>"""
        with pytest.raises(
            ValueError, match="GPX data must contain a <gpx> root element"
        ):
            Route(
                journal_id=1,
                name="Test Route",
                gpx_data=invalid_gpx,
            )

    def test_route_description_optional(self):
        """Test that description is optional."""
        route = Route(
            journal_id=1,
            name="Test Route",
            description=None,
        )
        assert route.description is None
