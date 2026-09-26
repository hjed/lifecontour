"""Tests for the GEAR_USAGE domain model: an entry holding many gear items."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core_shared.models.journals import GearUsageData, GearUsageItem
from core_shared.models.journals.exceptions import GearUsageDataValidationError

_NOW = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)


class TestGearUsageItem:
    """One gear item used on a journal, with an optional buffer window."""

    def test_valid_item_with_both_dates(self) -> None:
        gear_item_id = uuid4()
        checkout = _NOW - timedelta(days=2)
        checkin = _NOW - timedelta(days=1)

        item = GearUsageItem(
            gear_item_id=gear_item_id, checkout_date=checkout, checkin_date=checkin
        )

        assert item.gear_item_id == gear_item_id
        assert item.checkout_date == checkout
        assert item.checkin_date == checkin

    def test_dates_are_optional(self) -> None:
        item = GearUsageItem(gear_item_id=uuid4())

        assert item.checkout_date is None
        assert item.checkin_date is None

    @pytest.mark.parametrize("field", ["checkout_date", "checkin_date"])
    def test_one_date_alone_is_fine(self, field: str) -> None:
        item = GearUsageItem(gear_item_id=uuid4(), **{field: _NOW})

        assert getattr(item, field) == _NOW

    def test_checkin_before_checkout_is_refused(self) -> None:
        with pytest.raises(GearUsageDataValidationError) as exc_info:
            GearUsageItem(
                gear_item_id=uuid4(),
                checkout_date=_NOW,
                checkin_date=_NOW - timedelta(days=1),
            )

        assert "checkin_date: Must be after or equal to checkout_date" in str(
            exc_info.value
        )

    def test_a_naive_date_compares_as_utc(self) -> None:
        with pytest.raises(GearUsageDataValidationError):
            GearUsageItem(
                gear_item_id=uuid4(),
                checkout_date=_NOW,
                checkin_date=(_NOW - timedelta(hours=1)).replace(tzinfo=None),
            )

    def test_gear_item_is_required(self) -> None:
        with pytest.raises(GearUsageDataValidationError, match="gear_item_id"):
            GearUsageItem(gear_item_id=None)  # type: ignore[arg-type]


class TestGearUsageData:
    """The GEAR_USAGE entry of a journal and the items it holds."""

    def test_an_entry_holds_many_items_in_order(self) -> None:
        first, second = (
            GearUsageItem(gear_item_id=uuid4()),
            GearUsageItem(gear_item_id=uuid4()),
        )

        data = GearUsageData(journal_id=1, items=(first, second))

        assert data.items == (first, second)

    def test_an_entry_may_hold_no_items(self) -> None:
        assert GearUsageData(journal_id=1).items == ()

    def test_the_same_gear_item_twice_is_refused(self) -> None:
        gear_item_id = uuid4()

        with pytest.raises(GearUsageDataValidationError, match="items"):
            GearUsageData(
                journal_id=1,
                items=(
                    GearUsageItem(gear_item_id=gear_item_id),
                    GearUsageItem(gear_item_id=gear_item_id, checkin_date=_NOW),
                ),
            )

    def test_item_finds_one_by_gear_item(self) -> None:
        wanted = GearUsageItem(gear_item_id=uuid4())
        data = GearUsageData(
            journal_id=1, items=(GearUsageItem(gear_item_id=uuid4()), wanted)
        )

        assert data.item(wanted.gear_item_id) == wanted
        assert data.item(uuid4()) is None

    def test_with_item_adds_a_new_gear_item_at_the_end(self) -> None:
        existing = GearUsageItem(gear_item_id=uuid4())
        added = GearUsageItem(gear_item_id=uuid4())

        data = GearUsageData(journal_id=1, items=(existing,)).with_item(added)

        assert data.items == (existing, added)

    def test_with_item_replaces_that_gear_item_in_place(self) -> None:
        first = GearUsageItem(gear_item_id=uuid4())
        second = GearUsageItem(gear_item_id=uuid4())
        updated = GearUsageItem(gear_item_id=first.gear_item_id, checkin_date=_NOW)

        data = GearUsageData(journal_id=1, items=(first, second)).with_item(updated)

        assert data.items == (updated, second)

    def test_without_item_removes_only_that_gear_item(self) -> None:
        first = GearUsageItem(gear_item_id=uuid4())
        second = GearUsageItem(gear_item_id=uuid4())

        data = GearUsageData(journal_id=1, items=(first, second)).without_item(
            first.gear_item_id
        )

        assert data.items == (second,)
