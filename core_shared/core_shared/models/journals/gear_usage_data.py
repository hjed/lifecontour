import dataclasses
from datetime import datetime
from uuid import UUID

from core_shared.models.journals.exceptions import GearUsageDataValidationError


@dataclasses.dataclass(frozen=True, kw_only=True)
class GearUsageData:
    """Domain model for gear usage data.

    This represents the type-specific data for a GEAR_USAGE journal entry.
    """

    journal_id: int | None = None
    gear_item_id: UUID
    checkout_date: datetime | None = None
    checkin_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate data fields upon initialization."""
        # Validate gear_item_id
        if not self.gear_item_id:
            raise GearUsageDataValidationError("gear_item_id", "Required")

        if self.checkout_date is not None and not isinstance(
            self.checkout_date, datetime
        ):
            raise GearUsageDataValidationError(
                "checkout_date", "Must be a datetime or None"
            )

        if self.checkin_date is not None and not isinstance(
            self.checkin_date, datetime
        ):
            raise GearUsageDataValidationError(
                "checkin_date", "Must be a datetime or None"
            )

        if self.checkout_date is not None and self.checkin_date is not None:
            chk_out = self.checkout_date
            chk_in = self.checkin_date

            if chk_out.tzinfo is None and chk_in.tzinfo is not None:
                from datetime import UTC

                chk_out = chk_out.replace(tzinfo=UTC)
            elif chk_in.tzinfo is None and chk_out.tzinfo is not None:
                from datetime import UTC

                chk_in = chk_in.replace(tzinfo=UTC)

            if chk_out > chk_in:
                raise GearUsageDataValidationError(
                    "checkin_date", "Must be after or equal to checkout_date"
                )
