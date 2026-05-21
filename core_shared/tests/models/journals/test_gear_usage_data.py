"""Tests for the GearUsageData domain model."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core_shared.models.journals import GearUsageData
from core_shared.models.journals.exceptions import GearUsageDataValidationError


def test_gear_usage_data_valid() -> None:
    """Test creating a valid GearUsageData object."""
    journal_id = 1
    gear_item_id = uuid4()
    now = datetime.now(UTC)
    checkout_date = now - timedelta(days=2)
    checkin_date = now - timedelta(days=1)

    data = GearUsageData(
        journal_id=journal_id,
        gear_item_id=gear_item_id,
        checkout_date=checkout_date,
        checkin_date=checkin_date,
    )

    assert data.journal_id == journal_id
    assert data.gear_item_id == gear_item_id
    assert data.checkout_date == checkout_date
    assert data.checkin_date == checkin_date


def test_gear_usage_data_no_dates() -> None:
    """Test creating a GearUsageData object without dates."""
    journal_id = 1
    gear_item_id = uuid4()

    data = GearUsageData(
        journal_id=journal_id,
        gear_item_id=gear_item_id,
    )

    assert data.journal_id == journal_id
    assert data.gear_item_id == gear_item_id
    assert data.checkout_date is None
    assert data.checkin_date is None


def test_gear_usage_data_checkout_only() -> None:
    """Test creating a GearUsageData object with only a checkout date."""
    journal_id = 1
    gear_item_id = uuid4()
    now = datetime.now(UTC)

    data = GearUsageData(
        journal_id=journal_id,
        gear_item_id=gear_item_id,
        checkout_date=now,
    )

    assert data.journal_id == journal_id
    assert data.gear_item_id == gear_item_id
    assert data.checkout_date == now
    assert data.checkin_date is None


def test_gear_usage_data_checkin_only() -> None:
    """Test creating a GearUsageData object with only a checkin date."""
    journal_id = 1
    gear_item_id = uuid4()
    now = datetime.now(UTC)

    data = GearUsageData(
        journal_id=journal_id,
        gear_item_id=gear_item_id,
        checkin_date=now,
    )

    assert data.journal_id == journal_id
    assert data.gear_item_id == gear_item_id
    assert data.checkout_date is None
    assert data.checkin_date == now


def test_gear_usage_data_invalid_dates() -> None:
    """Test that checkout_date must be before or equal to checkin_date."""
    journal_id = 1
    gear_item_id = uuid4()
    now = datetime.now(UTC)
    checkout_date = now
    checkin_date = now - timedelta(days=1)

    with pytest.raises(GearUsageDataValidationError) as exc_info:
        GearUsageData(
            journal_id=journal_id,
            gear_item_id=gear_item_id,
            checkout_date=checkout_date,
            checkin_date=checkin_date,
        )

    assert "checkin_date: Must be after or equal to checkout_date" in str(
        exc_info.value
    )
