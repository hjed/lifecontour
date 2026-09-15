# ruff: noqa: E402
"""Tests for Snipe-IT maintenance data transformer."""

import hashlib
import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

import pytest
from core_shared.models.journals.constants import MaintenanceType

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
            ("Upgrade", "upgrading gear"),
            ("Calibration", "calibration"),
            ("Software Support", "software support"),
            ("Hardware Support", "hardware support"),
            ("Configuration Change", "configuration change"),
        ],
    )
    def test_known_type_mapping(
        self, snipeit_type: str, expected_app_type: str
    ) -> None:
        """Known Snipe-IT types map to correct app types."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset": {"id": 10, "name": "Test Asset"},
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
                "asset": {"id": 10, "name": "Test Asset"},
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
                "asset": {"id": 10, "name": "Test Asset"},
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
                "asset": {"id": 42, "name": "Test Asset"},
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

    def test_html_entities_are_decoded_once(self) -> None:
        """Snipe-IT HTML-escapes text on output; the journal gets the raw text."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 17,
                "asset": {"id": 51, "name": "Canyoneroo 50m"},
                "title": "Split Canyoneroo 50 -&gt; 34 + 15",
                "notes": "Clean &amp; re apply, then write &amp;amp; literally",
            }
        )
        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )

        assert result.journal_data["title"] == "Split Canyoneroo 50 -> 34 + 15"
        assert (
            result.journal_data["content"]
            == "Clean & re apply, then write &amp; literally"
        )

    def test_missing_optional_fields(self) -> None:
        """Minimal maintenance with only required fields maps correctly."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset": {"id": 10, "name": "Test Asset"},
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
                "asset": {"id": 10, "name": "Test Asset"},
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
            "asset": {"id": 10, "name": "Test Asset"},
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
            "asset": {"id": 10, "name": "Test Asset"},
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

    def test_record_synced_before_lossless_types_is_synced_again(self) -> None:
        """The legacy hash covered only the record, and matching it would skip the
        re-import that corrects a type an earlier mapping collapsed."""
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset": {"id": 10, "name": "Test Asset"},
                "title": "Test",
                "asset_maintenance_type": "Upgrade",
                "start_date": {"date": "2024-01-01"},
            }
        )
        legacy_hash = hashlib.sha256(maintenance.model_dump_json().encode()).hexdigest()

        result = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="u1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )

        assert result.version_hash != legacy_hash


class TestResolveInboundMaintenanceType:
    """A re-import keeps a local type Snipe-IT cannot tell apart from its own."""

    def test_retiring_gear_pushed_as_maintenance_is_kept(self) -> None:
        assert (
            SnipeItMaintenanceTransformer.resolve_inbound_maintenance_type(
                "Maintenance", existing_type="retiring gear"
            )
            == "retiring gear"
        )

    def test_kind_changed_in_snipeit_replaces_retiring_gear(self) -> None:
        assert (
            SnipeItMaintenanceTransformer.resolve_inbound_maintenance_type(
                "Repair", existing_type="retiring gear"
            )
            == "repairing gear"
        )

    def test_type_collapsed_by_an_earlier_mapping_is_corrected(self) -> None:
        assert (
            SnipeItMaintenanceTransformer.resolve_inbound_maintenance_type(
                "Upgrade", existing_type="routine maintenance"
            )
            == "upgrading gear"
        )

    def test_new_import_takes_the_mapped_type(self) -> None:
        assert (
            SnipeItMaintenanceTransformer.resolve_inbound_maintenance_type(
                "Calibration", existing_type=None
            )
            == "calibration"
        )

    def test_missing_snipeit_type_takes_the_default(self) -> None:
        assert (
            SnipeItMaintenanceTransformer.resolve_inbound_maintenance_type(
                None, existing_type="retiring gear"
            )
            == "routine maintenance"
        )


class TestReverseMaintenanceTypeMapping:
    """Tests for app → Snipe-IT maintenance type mapping."""

    @pytest.mark.parametrize(
        ("app_type", "expected_snipeit_type"),
        [
            ("routine maintenance", "Maintenance"),
            ("repairing gear", "Repair"),
            ("routine inspection", "PAT Test"),
            ("upgrading gear", "Upgrade"),
            ("calibration", "Calibration"),
            ("software support", "Software Support"),
            ("hardware support", "Hardware Support"),
            ("configuration change", "Configuration Change"),
            ("retiring gear", "Maintenance"),
        ],
    )
    def test_reverse_known_type_mapping(
        self, app_type: str, expected_snipeit_type: str
    ) -> None:
        """Known app maintenance types map back to Snipe-IT types."""
        result = SnipeItMaintenanceTransformer.reverse_transform(
            title="Test Maintenance",
            content="Some notes",
            maintenance_type=app_type,
            start_date="2024-06-01",
            end_date="2024-06-02",
        )
        assert result["asset_maintenance_type"] == expected_snipeit_type

    def test_reverse_unknown_type_defaults(self) -> None:
        """Unknown app types default to 'Maintenance' in Snipe-IT."""
        result = SnipeItMaintenanceTransformer.reverse_transform(
            title="Test",
            content="",
            maintenance_type="some unknown type",
        )
        assert result["asset_maintenance_type"] == "Maintenance"


class TestMaintenanceTypeRoundTrip:
    """A Snipe-IT kind imported and pushed back is the kind it started as."""

    @pytest.mark.parametrize(
        "snipeit_type",
        [
            "Maintenance",
            "Repair",
            "Upgrade",
            "PAT Test",
            "Calibration",
            "Software Support",
            "Hardware Support",
            "Configuration Change",
        ],
    )
    def test_every_snipeit_kind_survives_import_and_push(
        self, snipeit_type: str
    ) -> None:
        maintenance = SnipeItMaintenance.model_validate(
            {
                "id": 1,
                "asset": {"id": 10, "name": "Test Asset"},
                "title": "Test",
                "asset_maintenance_type": snipeit_type,
                "start_date": {"date": "2024-01-01"},
            }
        )
        imported = SnipeItMaintenanceTransformer.transform(
            maintenance,
            user_id="user-1",
            gear_item_id="00000000-0000-0000-0000-000000000001",
        )

        pushed = SnipeItMaintenanceTransformer.reverse_transform(
            title="Test",
            content="",
            maintenance_type=imported.gear_maintenance_data["maintenance_type"],
        )

        assert pushed["asset_maintenance_type"] == snipeit_type

    def test_every_app_kind_but_retirement_has_its_own_snipeit_kind(self) -> None:
        pushed_kinds = {
            SnipeItMaintenanceTransformer.reverse_transform(
                title="Test", content="", maintenance_type=member.value
            )["asset_maintenance_type"]
            for member in MaintenanceType
            if member is not MaintenanceType.RETIRING_GEAR
        }

        assert len(pushed_kinds) == len(MaintenanceType) - 1


class TestReverseTransformPayload:
    """Tests for reverse transform payload structure."""

    def test_full_payload(self) -> None:
        """Full reverse transform includes title, notes, dates, and type."""
        result = SnipeItMaintenanceTransformer.reverse_transform(
            title="Rope Inspection",
            content="Checked all points",
            maintenance_type="routine inspection",
            start_date="2024-06-01",
            end_date="2024-06-02",
        )
        assert result["name"] == "Rope Inspection"
        assert result["notes"] == "Checked all points"
        assert result["start_date"] == "2024-06-01"
        assert result["completion_date"] == "2024-06-02"
        assert result["asset_maintenance_type"] == "PAT Test"

    def test_text_is_sent_unescaped(self) -> None:
        """Snipe-IT escapes on output, so escaping here would double-escape."""
        result = SnipeItMaintenanceTransformer.reverse_transform(
            title="Split Canyoneroo 50 -> 34 + 15",
            content="Clean & re apply",
            maintenance_type="routine maintenance",
        )
        assert result["name"] == "Split Canyoneroo 50 -> 34 + 15"
        assert result["notes"] == "Clean & re apply"

    def test_minimal_payload(self) -> None:
        """Minimal reverse transform with only title and type."""
        result = SnipeItMaintenanceTransformer.reverse_transform(
            title="Quick Check",
            content="",
            maintenance_type="routine maintenance",
        )
        assert result["name"] == "Quick Check"
        assert result["notes"] == ""
        assert result["asset_maintenance_type"] == "Maintenance"
        assert "start_date" not in result
        assert "completion_date" not in result

    def test_start_date_only(self) -> None:
        """Payload with start_date but no end_date."""
        result = SnipeItMaintenanceTransformer.reverse_transform(
            title="Test",
            content="",
            maintenance_type="routine maintenance",
            start_date="2024-06-01",
        )
        assert result["start_date"] == "2024-06-01"
        assert "completion_date" not in result
