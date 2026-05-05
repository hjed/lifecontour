import dataclasses
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from core_shared.models.journals.constants import (
    MAX_MAINTENANCE_TYPE_LENGTH,
    MAX_RETIREMENT_REASON_LENGTH,
    VALID_MAINTENANCE_TYPES,
)
from core_shared.models.journals.exceptions import GearMaintenanceDataValidationError

from .outdoor_activity_subtypes import OutdoorActivitySubtype


@dataclasses.dataclass(frozen=True, kw_only=True)
class GearMaintenanceData:
    """Domain model for gear maintenance data.

    This represents the type-specific data for a GEAR_MAINTENANCE journal entry.
    """

    journal_id: int | None = None
    gear_item_id: UUID
    maintenance_type: str
    activity_types: list[str] | None = None
    retirement_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate data fields upon initialization."""
        # Validate gear_item_id
        if not self.gear_item_id:
            raise GearMaintenanceDataValidationError("gear_item_id", "Required")

        # Validate maintenance_type
        if not self.maintenance_type:
            raise GearMaintenanceDataValidationError("maintenance_type", "Required")

        if not isinstance(self.maintenance_type, str):
            raise GearMaintenanceDataValidationError(
                "maintenance_type", "Must be a string"
            )

        if len(self.maintenance_type) > MAX_MAINTENANCE_TYPE_LENGTH:
            raise GearMaintenanceDataValidationError(
                "maintenance_type",
                f"Must be <= {MAX_MAINTENANCE_TYPE_LENGTH} characters",
            )

        if self.maintenance_type not in VALID_MAINTENANCE_TYPES:
            raise GearMaintenanceDataValidationError(
                "maintenance_type",
                f"Must be one of: {', '.join(VALID_MAINTENANCE_TYPES)}",
            )

        # Validate activity_types
        if self.activity_types is not None:
            if not isinstance(self.activity_types, Sequence) or isinstance(
                self.activity_types, str
            ):
                raise GearMaintenanceDataValidationError(
                    "activity_types", "Must be a list of strings or None"
                )

            valid_subtypes = {s.value for s in OutdoorActivitySubtype}
            for item in self.activity_types:
                if not isinstance(item, str):
                    raise GearMaintenanceDataValidationError(
                        "activity_types", "All items must be strings"
                    )
                if item not in valid_subtypes:
                    raise GearMaintenanceDataValidationError(
                        "activity_types",
                        f"Invalid activity type. Must be one of: {', '.join(sorted(valid_subtypes))}",
                    )

        # Validate retirement_reason
        if self.retirement_reason is not None:
            if not isinstance(self.retirement_reason, str):
                raise GearMaintenanceDataValidationError(
                    "retirement_reason", "Must be a string or None"
                )
            if len(self.retirement_reason) > MAX_RETIREMENT_REASON_LENGTH:
                raise GearMaintenanceDataValidationError(
                    "retirement_reason",
                    f"Must be <= {MAX_RETIREMENT_REASON_LENGTH} characters",
                )

        if self.maintenance_type == "retiring gear":
            if not self.retirement_reason or not self.retirement_reason.strip():
                raise GearMaintenanceDataValidationError(
                    "retirement_reason",
                    "Required when maintenance_type is 'retiring gear'",
                )
