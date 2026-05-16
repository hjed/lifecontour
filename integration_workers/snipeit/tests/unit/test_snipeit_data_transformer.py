"""Tests for Snipe-IT data transformer (Asset → GearItem mapping)."""

from datetime import date

from core_shared.models.journals.gear_item import GearItem

from snipeit_data_transformer import SnipeItDataTransformer, TransformResult
from snipeit_models import (
    SnipeItAsset,
    SnipeItDateObject,
    SnipeItNestedObject,
)


def _make_asset(**overrides: object) -> SnipeItAsset:
    """Create a SnipeItAsset with sensible defaults and optional overrides."""
    defaults: dict[str, object] = {
        "id": 42,
        "name": "Climbing Rope",
        "asset_tag": "GEAR-001",
        "serial": "SN-12345",
        "model": SnipeItNestedObject(id=10, name="Dynamic Rope 60m"),
        "manufacturer": SnipeItNestedObject(id=5, name="Petzl"),
        "purchase_date": SnipeItDateObject(date="2024-06-15"),
    }
    defaults.update(overrides)
    return SnipeItAsset.model_validate(defaults)


class TestTransformerFullAsset:
    """Tests for transforming a complete Snipe-IT asset."""

    def test_all_fields_mapped_correctly(self) -> None:
        """Full asset produces correct GearItem entity."""
        asset = _make_asset()
        result = SnipeItDataTransformer.transform(asset, user_id="user-1")

        assert isinstance(result, TransformResult)
        assert isinstance(result.gear_item, GearItem)
        assert result.gear_item.name == "Climbing Rope"
        assert result.gear_item.serial_number == "SN-12345"
        assert result.gear_item.model == "Dynamic Rope 60m"
        assert result.gear_item.manufacturer == "Petzl"
        assert result.gear_item.purchase_date == date(2024, 6, 15)
        assert result.gear_item.user_id == "user-1"
        assert result.snipeit_asset_id == 42

    def test_version_hash_is_deterministic(self) -> None:
        """Same asset input produces the same version hash."""
        asset = _make_asset()
        r1 = SnipeItDataTransformer.transform(asset, user_id="u")
        r2 = SnipeItDataTransformer.transform(asset, user_id="u")
        assert r1.version_hash == r2.version_hash
        assert len(r1.version_hash) == 64  # SHA-256 hex

    def test_version_hash_changes_on_data_change(self) -> None:
        """Different asset data produces different version hash."""
        a1 = _make_asset(name="Rope A")
        a2 = _make_asset(name="Rope B")
        r1 = SnipeItDataTransformer.transform(a1, user_id="u")
        r2 = SnipeItDataTransformer.transform(a2, user_id="u")
        assert r1.version_hash != r2.version_hash


class TestTransformerMissingOptionalFields:
    """Tests for transformer handling of missing/optional fields."""

    def test_no_manufacturer(self) -> None:
        """Asset with no manufacturer maps manufacturer to None."""
        asset = _make_asset(manufacturer=None)
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.manufacturer is None

    def test_no_model(self) -> None:
        """Asset with no model maps model to None."""
        asset = _make_asset(model=None)
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.model is None

    def test_no_serial(self) -> None:
        """Asset with no serial maps serial_number to None."""
        asset = _make_asset(serial=None)
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.serial_number is None

    def test_no_purchase_date(self) -> None:
        """Asset with no purchase_date maps to None."""
        asset = _make_asset(purchase_date=None)
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.purchase_date is None

    def test_no_name_uses_asset_tag(self) -> None:
        """Asset with no name falls back to asset_tag."""
        asset = _make_asset(name=None)
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.name == "GEAR-001"


class TestTransformerNestedNulls:
    """Tests for nested objects with null inner values."""

    def test_model_with_null_name(self) -> None:
        """Model object present but name is null."""
        asset = _make_asset(model=SnipeItNestedObject(id=10, name=None))
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.model is None

    def test_manufacturer_with_null_name(self) -> None:
        """Manufacturer object present but name is null."""
        asset = _make_asset(manufacturer=SnipeItNestedObject(id=5, name=None))
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.manufacturer is None


class TestTransformerPurchaseDate:
    """Tests for purchase date parsing."""

    def test_valid_date_string(self) -> None:
        """Standard YYYY-MM-DD date parses correctly."""
        asset = _make_asset(purchase_date=SnipeItDateObject(date="2024-01-15"))
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.purchase_date == date(2024, 1, 15)

    def test_invalid_date_string_falls_back_to_none(self) -> None:
        """Invalid date string gracefully returns None."""
        asset = _make_asset(purchase_date=SnipeItDateObject(date="not-a-date"))
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.purchase_date is None

    def test_null_inner_date_string(self) -> None:
        """Date object with null inner date."""
        asset = _make_asset(purchase_date=SnipeItDateObject(date=None))
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.purchase_date is None


class TestTransformerFieldTruncation:
    """Tests for field length enforcement."""

    def test_long_name_truncated(self) -> None:
        """Name exceeding MAX_GEAR_ITEM_NAME_LENGTH is truncated."""
        long_name = "A" * 250
        asset = _make_asset(name=long_name)
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert len(result.gear_item.name) <= 200

    def test_long_model_truncated(self) -> None:
        """Model name exceeding MAX_GEAR_ITEM_FIELD_LENGTH is truncated."""
        asset = _make_asset(
            model=SnipeItNestedObject(id=1, name="M" * 250),
        )
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.model is not None
        assert len(result.gear_item.model) <= 200

    def test_long_serial_truncated(self) -> None:
        """Serial exceeding MAX_GEAR_ITEM_FIELD_LENGTH is truncated."""
        asset = _make_asset(serial="S" * 250)
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.serial_number is not None
        assert len(result.gear_item.serial_number) <= 200

    def test_long_manufacturer_truncated(self) -> None:
        """Manufacturer name exceeding limit is truncated."""
        asset = _make_asset(
            manufacturer=SnipeItNestedObject(id=1, name="M" * 250),
        )
        result = SnipeItDataTransformer.transform(asset, user_id="u")
        assert result.gear_item.manufacturer is not None
        assert len(result.gear_item.manufacturer) <= 200
