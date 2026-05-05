from uuid import uuid4

import pytest

from core_shared.models.journals.exceptions import GearMaintenanceDataValidationError
from core_shared.models.journals.gear_maintenance_data import GearMaintenanceData


def test_gear_maintenance_data_valid() -> None:
    """Test successful initialization of GearMaintenanceData."""
    gear_item_id = uuid4()
    data = GearMaintenanceData(
        journal_id=1,
        gear_item_id=gear_item_id,
        maintenance_type="routine maintenance",
        activity_types=["canyoning", "abseiling_trip"],
    )

    assert data.journal_id == 1
    assert data.gear_item_id == gear_item_id
    assert data.maintenance_type == "routine maintenance"
    assert data.activity_types == ["canyoning", "abseiling_trip"]
    assert data.retirement_reason is None


def test_gear_maintenance_data_retirement_reason_required() -> None:
    """Test that retirement_reason is required when maintenance_type is 'retiring gear'."""
    gear_item_id = uuid4()

    with pytest.raises(GearMaintenanceDataValidationError) as exc_info:
        GearMaintenanceData(
            gear_item_id=gear_item_id,
            maintenance_type="retiring gear",
        )
    assert exc_info.value.field == "retirement_reason"
    assert "Required when maintenance_type is 'retiring gear'" in str(exc_info.value)

    # Empty string should also fail
    with pytest.raises(GearMaintenanceDataValidationError) as exc_info:
        GearMaintenanceData(
            gear_item_id=gear_item_id,
            maintenance_type="retiring gear",
            retirement_reason="  ",
        )
    assert exc_info.value.field == "retirement_reason"


def test_gear_maintenance_data_retirement_reason_success() -> None:
    """Test successful initialization with retirement reason."""
    gear_item_id = uuid4()
    data = GearMaintenanceData(
        gear_item_id=gear_item_id,
        maintenance_type="retiring gear",
        retirement_reason="Core damaged",
    )
    assert data.maintenance_type == "retiring gear"
    assert data.retirement_reason == "Core damaged"


def test_gear_maintenance_data_invalid_gear_item_id() -> None:
    """Test validation fails with invalid gear_item_id."""
    with pytest.raises(GearMaintenanceDataValidationError) as exc_info:
        GearMaintenanceData(
            gear_item_id=None,  # type: ignore
            maintenance_type="routine maintenance",
        )
    assert exc_info.value.field == "gear_item_id"


def test_gear_maintenance_data_invalid_maintenance_type() -> None:
    """Test validation fails with invalid maintenance_type."""
    gear_item_id = uuid4()

    # Missing type
    with pytest.raises(GearMaintenanceDataValidationError) as exc_info:
        GearMaintenanceData(
            gear_item_id=gear_item_id,
            maintenance_type="",
        )
    assert exc_info.value.field == "maintenance_type"

    # Invalid string value
    with pytest.raises(GearMaintenanceDataValidationError) as exc_info:
        GearMaintenanceData(
            gear_item_id=gear_item_id,
            maintenance_type="cleaning",
        )
    assert exc_info.value.field == "maintenance_type"
    assert "Must be one of" in str(exc_info.value)


def test_gear_maintenance_data_invalid_activity_types() -> None:
    """Test validation fails with invalid activity_types."""
    gear_item_id = uuid4()

    # Not a list
    with pytest.raises(GearMaintenanceDataValidationError) as exc_info:
        GearMaintenanceData(
            gear_item_id=gear_item_id,
            maintenance_type="routine maintenance",
            activity_types="Canyoning",  # type: ignore
        )
    assert exc_info.value.field == "activity_types"

    # List of non-strings
    with pytest.raises(GearMaintenanceDataValidationError) as exc_info:
        GearMaintenanceData(
            gear_item_id=gear_item_id,
            maintenance_type="routine maintenance",
            activity_types=[123],  # type: ignore
        )
    assert exc_info.value.field == "activity_types"
    assert "All items must be strings" in str(exc_info.value)
