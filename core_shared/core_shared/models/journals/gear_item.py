"""GearItem entity for the journal domain.

GearItem represents a user-owned piece of gear (e.g. rope, harness, helmet).
Gear items are standalone entities, similar to activity templates.
They are referenced from GEAR_MAINTENANCE journal type data.

The data model is designed to be compatible with future SnipeIT sync:
name, model, serial_number, manufacturer match SnipeIT asset fields.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from .constants import MAX_GEAR_ITEM_FIELD_LENGTH, MAX_GEAR_ITEM_NAME_LENGTH
from .exceptions import GearItemValidationError


@dataclass
class GearItem:
    """
    GearItem entity for user-owned gear.

    Gear items are user-owned and searchable by name. They are referenced
    from GEAR_MAINTENANCE journals to track maintenance, inspection,
    and retirement of equipment.

    Attributes:
        name: Gear item name (required, max 200 chars)
        user_id: Owner user ID (required)
        id: UUID primary key (auto-generated if not provided)
        model: Model name/number (nullable, max 200 chars)
        serial_number: Serial number (nullable, max 200 chars)
        purchase_date: Date of purchase (nullable)
        manufacturer: Manufacturer name (nullable, max 200 chars)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    name: str
    user_id: str
    id: str | None = None
    model: str | None = None
    serial_number: str | None = None
    purchase_date: date | None = None
    manufacturer: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate and set defaults for gear item properties."""
        if self.id is None:
            self.id = str(uuid.uuid4())
        self._validate_id()
        self._validate_name()
        self._validate_user_id()
        self._validate_optional_string_field("model", self.model)
        self._validate_optional_string_field("serial_number", self.serial_number)
        self._validate_optional_string_field("manufacturer", self.manufacturer)

    def _validate_id(self) -> None:
        """Validate id is a valid UUID string."""
        if self.id is not None:
            try:
                uuid.UUID(self.id)
            except ValueError as e:
                raise GearItemValidationError("id", "ID must be a valid UUID") from e

    def _validate_name(self) -> None:
        """Validate name is non-empty and within length limit."""
        if not self.name or not self.name.strip():
            raise GearItemValidationError(
                "name", "Gear item name must be a non-empty string"
            )
        if len(self.name) > MAX_GEAR_ITEM_NAME_LENGTH:
            raise GearItemValidationError(
                "name",
                f"Gear item name must not exceed {MAX_GEAR_ITEM_NAME_LENGTH} characters",
            )

    def _validate_user_id(self) -> None:
        """Validate user_id is non-empty."""
        if not self.user_id or not self.user_id.strip():
            raise GearItemValidationError(
                "user_id", "User ID must be a non-empty string"
            )

    def _validate_optional_string_field(
        self, field_name: str, value: str | None
    ) -> None:
        """Validate an optional string field's length."""
        if value is not None and len(value) > MAX_GEAR_ITEM_FIELD_LENGTH:
            raise GearItemValidationError(
                field_name,
                f"{field_name} must not exceed {MAX_GEAR_ITEM_FIELD_LENGTH} characters",
            )
