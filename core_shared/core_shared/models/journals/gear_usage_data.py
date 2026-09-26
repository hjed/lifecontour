"""GEAR_USAGE type data: the gear items a journal records using.

A journal has the GEAR_USAGE type while it has a ``journal_gear_usage_data``
row — the entry — and the entry holds any number of items, one per gear item,
each with its own optional checkout/check-in buffer window.
"""

import dataclasses
from datetime import UTC, datetime
from uuid import UUID

from core_shared.models.journals.exceptions import GearUsageDataValidationError


@dataclasses.dataclass(frozen=True, kw_only=True)
class GearUsageItem:
    """One gear item used on a journal.

    ``checkout_date`` / ``checkin_date`` are optional buffers (pack the day
    before, return the day after); without them the journal's event range is the
    usage window.
    """

    gear_item_id: UUID
    checkout_date: datetime | None = None
    checkin_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate data fields upon initialization."""
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
            # A naive datetime is treated as UTC when compared with an aware one.
            if (chk_out.tzinfo is None) != (chk_in.tzinfo is None):
                chk_out = chk_out.replace(tzinfo=chk_out.tzinfo or UTC)
                chk_in = chk_in.replace(tzinfo=chk_in.tzinfo or UTC)

            if chk_out > chk_in:
                raise GearUsageDataValidationError(
                    "checkin_date", "Must be after or equal to checkout_date"
                )


@dataclasses.dataclass(frozen=True, kw_only=True)
class GearUsageData:
    """The GEAR_USAGE entry of a journal and the gear items it holds.

    Items are ordered by when they were added. A gear item appears at most once:
    it is the item's identity on the journal, and the Snipe-IT checkout of the
    (journal, asset) pair is keyed by it.
    """

    journal_id: int | None = None
    items: tuple[GearUsageItem, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse an entry listing the same gear item twice."""
        seen: set[UUID] = set()
        for item in self.items:
            if item.gear_item_id in seen:
                raise GearUsageDataValidationError(
                    "items", f"Gear item {item.gear_item_id} is listed more than once"
                )
            seen.add(item.gear_item_id)

    def item(self, gear_item_id: UUID) -> GearUsageItem | None:
        """The item for ``gear_item_id``, or ``None`` when it is not on the entry."""
        return next(
            (item for item in self.items if item.gear_item_id == gear_item_id), None
        )

    def with_item(self, item: GearUsageItem) -> GearUsageData:
        """This entry with ``item`` added, or replacing its gear item's item in place."""
        if self.item(item.gear_item_id) is None:
            return dataclasses.replace(self, items=(*self.items, item))
        return dataclasses.replace(
            self,
            items=tuple(
                item if existing.gear_item_id == item.gear_item_id else existing
                for existing in self.items
            ),
        )

    def without_item(self, gear_item_id: UUID) -> GearUsageData:
        """This entry without the item for ``gear_item_id``."""
        return dataclasses.replace(
            self,
            items=tuple(i for i in self.items if i.gear_item_id != gear_item_id),
        )
