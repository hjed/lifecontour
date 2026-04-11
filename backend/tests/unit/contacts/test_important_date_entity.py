"""Unit tests for important dates entity and validation."""

import pytest
from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.important_date_types import (
    CustomDateType,
    DatePrecision,
    ImportantDateType,
)


def test_important_date_valid_full_precision():
    """Test creating a valid full precision date."""
    date = ImportantDate(
        contact_id=1,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=1990,
        month=5,
        day=15,
    )
    assert date.year == 1990
    assert date.month == 5
    assert date.day == 15


def test_important_date_valid_day_month():
    """Test creating a valid day_month precision date."""
    date = ImportantDate(
        contact_id=1,
        date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
        precision=DatePrecision.DAY_MONTH,
        year=None,
        month=10,
        day=20,
    )
    assert date.year is None
    assert date.month == 10
    assert date.day == 20


def test_important_date_valid_year():
    """Test creating a valid year precision date."""
    date = ImportantDate(
        contact_id=1,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2020,
        month=None,
        day=None,
    )
    assert date.year == 2020
    assert date.month is None
    assert date.day is None


def test_important_date_invalid_full_missing_parts():
    """Test full precision requires all parts."""
    with pytest.raises(ValueError, match="Full precision requires"):
        ImportantDate(
            contact_id=1,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.FULL,
            year=1990,
            month=5,
            day=None,
        )


def test_important_date_invalid_day_month_missing_parts():
    """Test day_month precision requires month and day."""
    with pytest.raises(ValueError, match="Day/Month precision requires"):
        ImportantDate(
            contact_id=1,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.DAY_MONTH,
            year=None,
            month=5,
            day=None,
        )


def test_important_date_invalid_year_missing_parts():
    """Test year precision requires year."""
    with pytest.raises(ValueError, match="Year precision requires"):
        ImportantDate(
            contact_id=1,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.YEAR,
            year=None,
            month=None,
            day=None,
        )


def test_important_date_invalid_month_range():
    """Test month must be between 1 and 12."""
    with pytest.raises(ValueError, match="be between 1 and 12"):
        ImportantDate(
            contact_id=1,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.DAY_MONTH,
            year=None,
            month=13,
            day=1,
        )


def test_important_date_invalid_day_range():
    """Test day must be between 1 and 31."""
    with pytest.raises(ValueError, match="be between 1 and 31"):
        ImportantDate(
            contact_id=1,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.DAY_MONTH,
            year=None,
            month=1,
            day=32,
        )


def test_important_date_custom_type_requires_id():
    """Test custom date type requires custom_date_type_id."""
    with pytest.raises(ValueError, match="custom_date_type_id is required"):
        ImportantDate(
            contact_id=1,
            date_type=ImportantDateType.CUSTOM,
            precision=DatePrecision.YEAR,
            year=2020,
        )

    # Valid custom
    date = ImportantDate(
        contact_id=1,
        date_type=ImportantDateType.CUSTOM,
        precision=DatePrecision.YEAR,
        year=2020,
        custom_date_type_id=1,
    )
    assert date.custom_date_type_id == 1


def test_important_date_builtin_type_forbids_custom_id():
    """Test built-in types cannot have custom_date_type_id."""
    with pytest.raises(ValueError, match="custom_date_type_id should only be set"):
        ImportantDate(
            contact_id=1,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.YEAR,
            year=2020,
            custom_date_type_id=1,
        )


def test_custom_date_type_validation():
    """Test custom date type entity validation."""
    with pytest.raises(ValueError, match="Name cannot be empty"):
        CustomDateType(name="")

    with pytest.raises(ValueError, match="cannot exceed 100 characters"):
        CustomDateType(name="a" * 101)

    ctype = CustomDateType(name="Graduation")
    assert ctype.name == "Graduation"


def test_contact_get_birthday():
    """Test helper method to get birthday."""
    contact = Contact(first_name="John")
    assert contact.get_birthday() is None

    birthday = ImportantDate(
        contact_id=1,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.YEAR,
        year=1990,
    )

    anniv = ImportantDate(
        contact_id=1,
        date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2010,
    )

    contact.important_dates = [anniv, birthday]
    assert contact.get_birthday() == birthday
