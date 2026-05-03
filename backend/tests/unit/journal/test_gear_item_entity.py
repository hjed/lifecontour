"""Unit tests for the GearItem entity."""

from datetime import date, datetime

import pytest
from core_shared.models.journals.exceptions import GearItemValidationError
from core_shared.models.journals.gear_item import GearItem


class TestGearItemCreation:
    """Tests for valid GearItem creation."""

    def test_valid_creation_all_fields(self) -> None:
        """Test creating a GearItem with all fields provided."""
        item = GearItem(
            name="Climbing Rope 60m",
            user_id="user-123",
            model="Beal Stinger III",
            serial_number="SN-12345",
            purchase_date=date(2025, 6, 15),
            manufacturer="Beal",
        )
        assert item.name == "Climbing Rope 60m"
        assert item.user_id == "user-123"
        assert item.model == "Beal Stinger III"
        assert item.serial_number == "SN-12345"
        assert item.purchase_date == date(2025, 6, 15)
        assert item.manufacturer == "Beal"
        assert item.id is not None  # Auto-generated UUID

    def test_valid_creation_only_required_fields(self) -> None:
        """Test creating a GearItem with only required fields (name, user_id)."""
        item = GearItem(name="Harness", user_id="user-456")
        assert item.name == "Harness"
        assert item.user_id == "user-456"
        assert item.model is None
        assert item.serial_number is None
        assert item.purchase_date is None
        assert item.manufacturer is None

    def test_auto_generated_uuid_id(self) -> None:
        """Test that id is auto-generated as a valid UUID when not provided."""
        import uuid

        item = GearItem(name="Helmet", user_id="user-789")
        # Should be a valid UUID string
        parsed = uuid.UUID(item.id)
        assert str(parsed) == item.id

    def test_explicit_id_preserved(self) -> None:
        """Test that an explicitly provided id is preserved."""
        item = GearItem(
            name="Carabiner",
            user_id="user-123",
            id="550e8400-e29b-41d4-a716-446655440000",
        )
        assert item.id == "550e8400-e29b-41d4-a716-446655440000"

    def test_timestamps_default_none(self) -> None:
        """Test that timestamp fields default to None."""
        item = GearItem(name="Sling", user_id="user-123")
        assert item.created_at is None
        assert item.updated_at is None

    def test_timestamps_preserved(self) -> None:
        """Test that provided timestamps are preserved."""
        now = datetime(2025, 6, 15, 10, 30, 0)
        item = GearItem(
            name="Descender",
            user_id="user-123",
            created_at=now,
            updated_at=now,
        )
        assert item.created_at == now
        assert item.updated_at == now


class TestGearItemNameValidation:
    """Tests for name field validation."""

    def test_empty_name_raises_error(self) -> None:
        """Test validation fails when name is empty string."""
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="", user_id="user-123")
        assert exc_info.value.field == "name"
        assert "non-empty" in str(exc_info.value)

    def test_whitespace_only_name_raises_error(self) -> None:
        """Test validation fails when name is whitespace-only."""
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="   ", user_id="user-123")
        assert exc_info.value.field == "name"
        assert "non-empty" in str(exc_info.value)

    def test_name_exceeds_max_length_raises_error(self) -> None:
        """Test validation fails when name exceeds maximum length."""
        from core_shared.models.journals.constants import MAX_GEAR_ITEM_NAME_LENGTH

        long_name = "x" * (MAX_GEAR_ITEM_NAME_LENGTH + 1)
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name=long_name, user_id="user-123")
        assert exc_info.value.field == "name"
        assert str(MAX_GEAR_ITEM_NAME_LENGTH) in str(exc_info.value)

    def test_name_at_max_length_succeeds(self) -> None:
        """Test that name at exactly max length succeeds."""
        from core_shared.models.journals.constants import MAX_GEAR_ITEM_NAME_LENGTH

        name = "x" * MAX_GEAR_ITEM_NAME_LENGTH
        item = GearItem(name=name, user_id="user-123")
        assert item.name == name


class TestGearItemUserIdValidation:
    """Tests for user_id field validation."""

    def test_empty_user_id_raises_error(self) -> None:
        """Test validation fails when user_id is empty string."""
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="Rope", user_id="")
        assert exc_info.value.field == "user_id"
        assert "non-empty" in str(exc_info.value)

    def test_whitespace_only_user_id_raises_error(self) -> None:
        """Test validation fails when user_id is whitespace-only."""
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="Rope", user_id="   ")
        assert exc_info.value.field == "user_id"
        assert "non-empty" in str(exc_info.value)


class TestGearItemIdValidation:
    """Tests for id field validation."""

    def test_invalid_uuid_raises_error(self) -> None:
        """Test validation fails when id is not a valid UUID."""
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="Rope", user_id="user-123", id="not-a-uuid")
        assert exc_info.value.field == "id"
        assert "UUID" in str(exc_info.value)


class TestGearItemOptionalFieldLengths:
    """Tests for optional field length constraints."""

    def test_model_exceeds_max_length_raises_error(self) -> None:
        """Test validation fails when model exceeds maximum length."""
        from core_shared.models.journals.constants import (
            MAX_GEAR_ITEM_FIELD_LENGTH,
        )

        long_model = "x" * (MAX_GEAR_ITEM_FIELD_LENGTH + 1)
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="Rope", user_id="user-123", model=long_model)
        assert exc_info.value.field == "model"

    def test_serial_number_exceeds_max_length_raises_error(self) -> None:
        """Test validation fails when serial_number exceeds maximum length."""
        from core_shared.models.journals.constants import (
            MAX_GEAR_ITEM_FIELD_LENGTH,
        )

        long_serial = "x" * (MAX_GEAR_ITEM_FIELD_LENGTH + 1)
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="Rope", user_id="user-123", serial_number=long_serial)
        assert exc_info.value.field == "serial_number"

    def test_manufacturer_exceeds_max_length_raises_error(self) -> None:
        """Test validation fails when manufacturer exceeds maximum length."""
        from core_shared.models.journals.constants import (
            MAX_GEAR_ITEM_FIELD_LENGTH,
        )

        long_manufacturer = "x" * (MAX_GEAR_ITEM_FIELD_LENGTH + 1)
        with pytest.raises(GearItemValidationError) as exc_info:
            GearItem(name="Rope", user_id="user-123", manufacturer=long_manufacturer)
        assert exc_info.value.field == "manufacturer"

    def test_optional_fields_accept_valid_values(self) -> None:
        """Test that optional fields accept valid string values."""
        item = GearItem(
            name="Rope",
            user_id="user-123",
            model="Model X",
            serial_number="SN-999",
            manufacturer="Petzl",
        )
        assert item.model == "Model X"
        assert item.serial_number == "SN-999"
        assert item.manufacturer == "Petzl"

    def test_optional_fields_accept_none(self) -> None:
        """Test that optional fields accept None."""
        item = GearItem(
            name="Rope",
            user_id="user-123",
            model=None,
            serial_number=None,
            manufacturer=None,
            purchase_date=None,
        )
        assert item.model is None
        assert item.serial_number is None
        assert item.manufacturer is None
        assert item.purchase_date is None
