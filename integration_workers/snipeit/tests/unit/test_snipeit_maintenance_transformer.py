# ruff: noqa: E402
"""Tests for Snipe-IT maintenance data transformer."""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

import pytest

from snipeit_maintenance_transformer import (
    SnipeItMaintenanceTransformer,
)
from snipeit_models import SnipeItMaintenance


class TestMaintenanceTypeMapping:
    """Tests for Snipe-IT → app maintenance type mapping."""

    @pytest.mark.parametrize(
        ("snipeit_type", "expected_app_type"),
        [
            ("Maintenance", "routine maintenance"),
            ("Repair", "repairing gear"),
            ("PAT Test", "routine inspection"),
            ("Upgrade", "routine maintenance"),
            ("Hardware Support", "repairing gear"),
            ("Software Support", "routine maintenance"),
        ],
    )
    def test_known_type_mapping(
        self, snipeit_type: str, expected_app_type: str
    ) -> None:
        """Known Snipe-IT types map to correct app types."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset_id": 10,
                "title": "Test",
                "asset_maintenance_type": snipeit_type,
                "start_date": {"date": "2024-01-01"},
            }
        )
        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )
        assert result.gear_maintenance_data["maintenance_type"] == expected_app_type

    def test_unknown_type_defaults_to_routine_maintenance(self) -> None:
        """Unknown Snipe-IT type defaults to routine maintenance."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset_id": 10,
                "title": "Test",
                "asset_maintenance_type": "SomeNewType",
                "start_date": {"date": "2024-01-01"},
            }
        )
        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )
        assert result.gear_maintenance_data["maintenance_type"] == "routine maintenance"

    def test_none_type_defaults_to_routine_maintenance(self) -> None:
        """None maintenance type defaults to routine maintenance."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset_id": 10,
                "title": "Test",
                "start_date": {"date": "2024-01-01"},
            }
        )
        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )
        assert result.gear_maintenance_data["maintenance_type"] == "routine maintenance"


class TestMaintenanceFieldMapping:
    """Tests for field extraction from Snipe-IT maintenance records."""

    def test_full_field_mapping(self) -> None:
        """All fields are correctly extracted and mapped."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 101,
                "asset_id": 42,
                "title": "Annual Rope Inspection",
                "asset_maintenance_type": "Maintenance",
                "start_date": {"date": "2024-06-01"},
                "completion_date": {"date": "2024-06-02"},
                "notes": "Inspected for wear and damage",
            }
        )
        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )

        # Journal data
        assert result.journal_data["title"] == "Annual Rope Inspection"
        assert result.journal_data["content"] == "Inspected for wear and damage"
        assert result.journal_data["user_id"] == "user-1"
        assert result.journal_data["event_date_range_start"] is not None
        assert result.journal_data["event_date_range_end"] is not None

        # Gear maintenance data
        assert (
            result.gear_maintenance_data["gear_item_id"]
            == "00000000-0000-0000-0000-000000000001"
        )
        assert result.gear_maintenance_data["maintenance_type"] == "routine maintenance"

        # Metadata
        assert result.snipeit_maintenance_id == 101
        assert len(result.version_hash) == 64  # SHA-256 hex

    def test_missing_optional_fields(self) -> None:
        """Minimal maintenance with only required fields maps correctly."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset_id": 10,
            }
        )
        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )

        # Title defaults to a descriptive string
        assert result.journal_data["title"] is not None
        assert len(result.journal_data["title"]) > 0
        # Content is empty when no notes
        assert result.journal_data["content"] == ""
        # Dates should still be set (from current time fallback)
        assert result.journal_data["event_date_range_start"] is not None

    def test_title_fallback_without_title(self) -> None:
        """Missing title uses a generated fallback."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 5,
                "asset_id": 10,
                "asset_maintenance_type": "Repair",
            }
        )
        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )
        assert (
            "maintenance" in result.journal_data["title"].lower()
            or "repair" in result.journal_data["title"].lower()
        )


class TestMaintenanceVersionHash:
    """Tests for version hash generation."""

    def test_identical_inputs_same_hash(self) -> None:
        """Same maintenance record produces the same hash."""
        data = {
            "id": 1,
            "asset_id": 10,
            "title": "Test",
            "asset_maintenance_type": "Maintenance",
            "start_date": {"date": "2024-01-01"},
        }
        m1 = SnipeItMaintenance.model_validate(data)
        m2 = SnipeItMaintenance.model_validate(data)

        r1 = SnipeItMaintenanceTransformer.transform(
            m1, user_id="u1", gear_item_id="00000000-0000-0000-0000-000000000001"
        )
        r2 = SnipeItMaintenanceTransformer.transform(
            m2, user_id="u1", gear_item_id="00000000-0000-0000-0000-000000000001"
        )
        assert r1.version_hash == r2.version_hash

    def test_different_title_different_hash(self) -> None:
        """Changing the title produces a different hash."""
        base = {
            "id": 1,
            "asset_id": 10,
            "asset_maintenance_type": "Maintenance",
            "start_date": {"date": "2024-01-01"},
        }
        m1 = SnipeItMaintenance.model_validate({**base, "title": "Title A"})
        m2 = SnipeItMaintenance.model_validate({**base, "title": "Title B"})

        r1 = SnipeItMaintenanceTransformer.transform(
            m1, user_id="u1", gear_item_id="00000000-0000-0000-0000-000000000001"
        )
        r2 = SnipeItMaintenanceTransformer.transform(
            m2, user_id="u1", gear_item_id="00000000-0000-0000-0000-000000000001"
        )
        assert r1.version_hash != r2.version_hash
