"""Tests for Snipe-IT Pydantic response models."""

import pytest
from pydantic import ValidationError

from snipeit_models import (
    SnipeItAsset,
    SnipeItAssetListResponse,
    SnipeItAssignedTo,
    SnipeItDateObject,
    SnipeItMaintenance,
    SnipeItMaintenanceListResponse,
    SnipeItMaintenanceWriteResponse,
    SnipeItNestedObject,
)


class TestSnipeItNestedObject:
    """Tests for the SnipeItNestedObject model."""

    def test_parse_full_nested_object(self) -> None:
        """Full nested object with id and name parses correctly."""
        obj = SnipeItNestedObject.model_validate({"id": 5, "name": "Test Name"})
        assert obj.id == 5
        assert obj.name == "Test Name"

    def test_parse_null_name(self) -> None:
        """Nested object with null name."""
        obj = SnipeItNestedObject.model_validate({"id": 1, "name": None})
        assert obj.id == 1
        assert obj.name is None

    def test_parse_empty_dict(self) -> None:
        """Empty dict defaults to None fields."""
        obj = SnipeItNestedObject.model_validate({})
        assert obj.id is None
        assert obj.name is None


class TestSnipeItDateObject:
    """Tests for the SnipeItDateObject model."""

    def test_parse_date_with_date_field(self) -> None:
        """Date object with a date string parses correctly."""
        obj = SnipeItDateObject.model_validate(
            {"date": "2024-01-15", "formatted": "Jan 15, 2024"}
        )
        assert obj.date == "2024-01-15"
        assert obj.formatted == "Jan 15, 2024"

    def test_parse_null_date(self) -> None:
        """Date object with null date."""
        obj = SnipeItDateObject.model_validate({"date": None, "formatted": None})
        assert obj.date is None

    def test_parse_empty_dict(self) -> None:
        """Empty dict defaults to None."""
        obj = SnipeItDateObject.model_validate({})
        assert obj.date is None


class TestSnipeItAsset:
    """Tests for the SnipeItAsset model."""

    def test_parse_full_asset(self) -> None:
        """Full asset payload with all nested objects parses correctly."""
        data = {
            "id": 42,
            "name": "Climbing Rope",
            "asset_tag": "GEAR-001",
            "serial": "SN-12345",
            "model": {"id": 10, "name": "Dynamic Rope 60m"},
            "model_number": "DR-60",
            "manufacturer": {"id": 5, "name": "Petzl"},
            "status_label": {"id": 1, "name": "Deployable"},
            "category": {"id": 3, "name": "Ropes"},
            "location": {"id": 2, "name": "Garage"},
            "purchase_date": {"date": "2024-06-15", "formatted": "Jun 15, 2024"},
            "purchase_cost": "350.00",
            "notes": "60m single rope",
            "assigned_to": {"id": 1, "name": "John", "type": "user"},
            "updated_at": {
                "datetime": "2024-07-01 12:00:00",
                "formatted": "Jul 01, 2024",
            },
        }
        asset = SnipeItAsset.model_validate(data)

        assert asset.id == 42
        assert asset.name == "Climbing Rope"
        assert asset.asset_tag == "GEAR-001"
        assert asset.serial == "SN-12345"
        assert asset.model_name == "Dynamic Rope 60m"
        assert asset.manufacturer_name == "Petzl"
        assert asset.purchase_date_str == "2024-06-15"
        assert asset.model_number == "DR-60"
        assert asset.notes == "60m single rope"
        assert asset.assigned_to is not None
        assert asset.assigned_to.id == 1
        assert asset.assigned_to.name == "John"
        assert asset.assigned_to.type == "user"

    def test_parse_minimal_asset(self) -> None:
        """Asset with only required fields (id, asset_tag)."""
        data = {"id": 1, "asset_tag": "TAG-001"}
        asset = SnipeItAsset.model_validate(data)

        assert asset.id == 1
        assert asset.asset_tag == "TAG-001"
        assert asset.name is None
        assert asset.serial is None
        assert asset.model is None
        assert asset.manufacturer is None
        assert asset.purchase_date is None
        assert asset.assigned_to is None

    def test_convenience_properties_with_none_nested(self) -> None:
        """Convenience properties return None when nested objects are None."""
        asset = SnipeItAsset.model_validate({"id": 1, "asset_tag": "TAG-001"})
        assert asset.model_name is None
        assert asset.manufacturer_name is None
        assert asset.purchase_date_str is None

    def test_nested_object_with_null_name(self) -> None:
        """Nested objects with null name return None from convenience props."""
        data = {
            "id": 1,
            "asset_tag": "TAG-001",
            "model": {"id": 10, "name": None},
            "manufacturer": {"id": 5, "name": None},
        }
        asset = SnipeItAsset.model_validate(data)
        assert asset.model_name is None
        assert asset.manufacturer_name is None

    def test_purchase_date_null_date_string(self) -> None:
        """Purchase date object present but inner date is null."""
        data = {
            "id": 1,
            "asset_tag": "TAG-001",
            "purchase_date": {"date": None, "formatted": None},
        }
        asset = SnipeItAsset.model_validate(data)
        assert asset.purchase_date_str is None


class TestSnipeItAssetListResponse:
    """Tests for the paginated asset list response."""

    def test_parse_list_response(self) -> None:
        """Paginated response with rows parses correctly."""
        data = {
            "total": 2,
            "rows": [
                {"id": 1, "name": "Rope", "asset_tag": "GEAR-001"},
                {"id": 2, "name": "Harness", "asset_tag": "GEAR-002"},
            ],
        }
        response = SnipeItAssetListResponse.model_validate(data)
        assert response.total == 2
        assert len(response.rows) == 2
        assert response.rows[0].name == "Rope"
        assert response.rows[1].name == "Harness"

    def test_parse_empty_list(self) -> None:
        """Empty rows list."""
        data = {"total": 0, "rows": []}
        response = SnipeItAssetListResponse.model_validate(data)
        assert response.total == 0
        assert len(response.rows) == 0

    def test_parse_with_missing_rows(self) -> None:
        """Response with no rows key defaults to empty list."""
        data = {"total": 0}
        response = SnipeItAssetListResponse.model_validate(data)
        assert response.rows == []


class TestSnipeItAssignedTo:
    """Tests for the SnipeItAssignedTo model."""

    def test_parse_user_assignment(self) -> None:
        """User assignment with all fields parses correctly."""
        data = {
            "id": 1,
            "name": "John Doe",
            "username": "jdoe",
            "first_name": "John",
            "last_name": "Doe",
            "email": "jdoe@example.com",
            "type": "user",
        }
        assigned = SnipeItAssignedTo.model_validate(data)
        assert assigned.id == 1
        assert assigned.name == "John Doe"
        assert assigned.username == "jdoe"
        assert assigned.type == "user"

    def test_parse_location_assignment(self) -> None:
        """Location assignment parses correctly."""
        data = {"id": 5, "name": "Garage", "type": "location"}
        assigned = SnipeItAssignedTo.model_validate(data)
        assert assigned.id == 5
        assert assigned.type == "location"
        assert assigned.username is None

    def test_missing_type_raises_validation_error(self) -> None:
        """Missing required type field raises ValidationError."""
        with pytest.raises(ValidationError):
            SnipeItAssignedTo.model_validate({"id": 1, "name": "Test"})


class TestSnipeItMaintenance:
    """Tests for the SnipeItMaintenance model (GET response shape)."""

    def test_parse_full_maintenance_get_response(self) -> None:
        """Full GET response with nested asset object parses correctly."""
        data = {
            "id": 101,
            "title": "Annual Rope Inspection",
            "asset_maintenance_type": "Maintenance",
            "start_date": {"date": "2024-06-01", "formatted": "Jun 01, 2024"},
            "completion_date": {"date": "2024-06-02", "formatted": "Jun 02, 2024"},
            "notes": "Inspected rope for damage",
            "cost": "25.00",
            "supplier": {"id": 3, "name": "Gear Pro"},
            "asset": {"id": 42, "name": "Climbing Rope"},
            "updated_at": {
                "datetime": "2024-07-01 12:00:00",
                "formatted": "Jul 01, 2024",
            },
        }
        m = SnipeItMaintenance.model_validate(data)

        assert m.id == 101
        assert m.asset_id == 42
        assert m.title == "Annual Rope Inspection"
        assert m.asset_maintenance_type == "Maintenance"
        assert m.start_date_str == "2024-06-01"
        assert m.completion_date_str == "2024-06-02"
        assert m.notes == "Inspected rope for damage"
        assert m.cost == "25.00"
        assert m.supplier is not None
        assert m.supplier.name == "Gear Pro"
        assert m.asset is not None
        assert m.asset.name == "Climbing Rope"

    def test_asset_id_derived_from_nested_asset(self) -> None:
        """asset_id property derives value from asset.id."""
        data = {
            "id": 7,
            "asset": {"id": 42, "name": "Climbing Rope"},
            "title": "Inspection",
        }
        m = SnipeItMaintenance.model_validate(data)

        assert m.asset_id == 42
        assert m.asset is not None
        assert m.asset.id == 42

    def test_parse_minimal_maintenance(self) -> None:
        """Maintenance with only required field (id)."""
        m = SnipeItMaintenance.model_validate({"id": 1})

        assert m.id == 1
        assert m.asset_id is None
        assert m.title is None
        assert m.asset is None

    def test_asset_id_none_when_no_asset_object(self) -> None:
        """asset_id is None when no asset object provided."""
        m = SnipeItMaintenance.model_validate({"id": 1})
        assert m.asset_id is None

    def test_asset_id_none_when_asset_has_null_id(self) -> None:
        """asset object present but with null id gives asset_id as None."""
        data = {"id": 1, "asset": {"id": None, "name": "Test"}}
        m = SnipeItMaintenance.model_validate(data)
        assert m.asset_id is None
        assert m.asset is not None

    def test_convenience_properties_with_none_dates(self) -> None:
        """Convenience properties return None when date objects are None."""
        m = SnipeItMaintenance.model_validate({"id": 1})
        assert m.start_date_str is None
        assert m.completion_date_str is None

    def test_convenience_properties_with_null_date_values(self) -> None:
        """Convenience properties return None when date objects have null inner date."""
        data = {
            "id": 1,
            "start_date": {"date": None, "formatted": None},
            "completion_date": {"date": None, "formatted": None},
        }
        m = SnipeItMaintenance.model_validate(data)
        assert m.start_date_str is None
        assert m.completion_date_str is None


class TestSnipeItMaintenanceWriteResponse:
    """Tests for the SnipeItMaintenanceWriteResponse model (POST/PATCH shape)."""

    def test_parse_post_response_payload(self) -> None:
        """POST payload response with explicit asset_id parses correctly."""
        data = {
            "id": 501,
            "asset_id": 42,
            "title": "Rope Inspection",
            "asset_maintenance_type": "PAT Test",
            "start_date": {"date": "2024-06-01"},
            "completion_date": {"date": "2024-06-02"},
            "notes": "All ropes checked",
        }
        m = SnipeItMaintenanceWriteResponse.model_validate(data)

        assert m.id == 501
        assert m.asset_id == 42
        assert m.title == "Rope Inspection"

    def test_missing_asset_id_raises_validation_error(self) -> None:
        """POST/PATCH payload without asset_id raises ValidationError."""
        with pytest.raises(ValidationError):
            SnipeItMaintenanceWriteResponse.model_validate({"id": 1})

    def test_minimal_write_response(self) -> None:
        """Minimal POST/PATCH payload with required fields only."""
        m = SnipeItMaintenanceWriteResponse.model_validate({"id": 1, "asset_id": 10})
        assert m.id == 1
        assert m.asset_id == 10
        assert m.title is None


class TestSnipeItMaintenanceListResponse:
    """Tests for the paginated maintenance list response."""

    def test_parse_list_response(self) -> None:
        """Paginated response with rows parses correctly."""
        data = {
            "total": 2,
            "rows": [
                {"id": 1, "asset": {"id": 10, "name": "Rope"}, "title": "Inspection"},
                {"id": 2, "asset": {"id": 20, "name": "Harness"}, "title": "Repair"},
            ],
        }
        response = SnipeItMaintenanceListResponse.model_validate(data)
        assert response.total == 2
        assert len(response.rows) == 2
        assert response.rows[0].title == "Inspection"
        assert response.rows[0].asset_id == 10
        assert response.rows[1].title == "Repair"
        assert response.rows[1].asset_id == 20

    def test_parse_empty_list(self) -> None:
        """Empty rows list."""
        data = {"total": 0, "rows": []}
        response = SnipeItMaintenanceListResponse.model_validate(data)
        assert response.total == 0
        assert len(response.rows) == 0

    def test_parse_with_missing_rows(self) -> None:
        """Response with no rows key defaults to empty list."""
        data = {"total": 0}
        response = SnipeItMaintenanceListResponse.model_validate(data)
        assert response.rows == []
