"""
Unit tests for Contact serialization with important_dates.

Tests round-trip serialize/deserialize for contact important dates,
ensuring the outbox pipeline correctly preserves date data.
"""

from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.serialization import (
    deserialize_contact,
    serialize_contact,
)


class TestSerializeImportantDates:
    """Test serialization of important_dates on Contact entities."""

    def test_serialize_with_important_dates(self) -> None:
        """Contact with important_dates serializes them."""
        contact = Contact(
            first_name="Test",
            important_dates=[
                ImportantDate(
                    contact_id=1,
                    date_type=ImportantDateType.BIRTHDAY,
                    precision=DatePrecision.FULL,
                    year=1990,
                    month=5,
                    day=20,
                ),
                ImportantDate(
                    contact_id=1,
                    date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
                    precision=DatePrecision.DAY_MONTH,
                    month=6,
                    day=20,
                ),
            ],
        )

        result = serialize_contact(contact)

        assert "important_dates" in result
        assert len(result["important_dates"]) == 2

        birthday = result["important_dates"][0]
        assert birthday["date_type"] == "birthday"
        assert birthday["precision"] == "full"
        assert birthday["year"] == 1990
        assert birthday["month"] == 5
        assert birthday["day"] == 20
        assert "custom_date_type_id" in birthday
        assert birthday["custom_date_type_id"] is None

        anniversary = result["important_dates"][1]
        assert anniversary["date_type"] == "marriage_anniversary"
        assert anniversary["precision"] == "day_month"
        assert anniversary["year"] is None
        assert anniversary["month"] == 6
        assert anniversary["day"] == 20

    def test_serialize_with_none_important_dates(self) -> None:
        """Contact with None important_dates serializes as None."""
        contact = Contact(first_name="Test", important_dates=None)

        result = serialize_contact(contact)

        assert result["important_dates"] is None

    def test_serialize_with_empty_important_dates(self) -> None:
        """Contact with empty important_dates list serializes as empty list."""
        contact = Contact(first_name="Test", important_dates=[])

        result = serialize_contact(contact)

        assert result["important_dates"] == []


class TestDeserializeImportantDates:
    """Test deserialization of important_dates back to Contact."""

    def test_deserialize_with_important_dates(self) -> None:
        """Important dates in payload are deserialized to ImportantDate entities."""
        data = {
            "first_name": "Test",
            "important_dates": [
                {
                    "date_type": "birthday",
                    "precision": "full",
                    "year": 1990,
                    "month": 5,
                    "day": 20,
                    "custom_date_type_id": None,
                },
            ],
        }

        contact = deserialize_contact(data)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 1
        date = contact.important_dates[0]
        assert date.date_type == ImportantDateType.BIRTHDAY
        assert date.precision == DatePrecision.FULL
        assert date.year == 1990
        assert date.month == 5
        assert date.day == 20
        assert date.contact_id == 0

    def test_deserialize_with_none_important_dates(self) -> None:
        """None important_dates preserves None on Contact."""
        data = {
            "first_name": "Test",
            "important_dates": None,
        }

        contact = deserialize_contact(data)

        assert contact.important_dates is None

    def test_deserialize_without_important_dates_key(self) -> None:
        """Missing important_dates key in payload defaults to None."""
        data = {
            "first_name": "Test",
        }

        contact = deserialize_contact(data)

        assert contact.important_dates is None

    def test_deserialize_with_empty_important_dates(self) -> None:
        """Empty important_dates list is preserved."""
        data = {
            "first_name": "Test",
            "important_dates": [],
        }

        contact = deserialize_contact(data)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 0


class TestDeserializeMissingFirstName:
    """Test deserialization resilience when first_name is missing or empty.

    Google contacts may not have a first name. The transformer defaults to
    'Unknown', but outbox events could arrive without the field if the
    serialization path differs or the data was created by an older version.
    """

    def test_deserialize_without_first_name_key(self) -> None:
        """Missing first_name key defaults to 'Unknown'."""
        data = {
            "last_name": "Doe",
            "methods": [],
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Unknown"
        assert contact.last_name == "Doe"

    def test_deserialize_with_none_first_name(self) -> None:
        """None first_name defaults to 'Unknown'."""
        data = {
            "first_name": None,
            "last_name": "Smith",
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Unknown"

    def test_deserialize_with_empty_first_name(self) -> None:
        """Empty string first_name defaults to 'Unknown'."""
        data = {
            "first_name": "   ",
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Unknown"

    def test_deserialize_with_valid_first_name_still_works(self) -> None:
        """Valid first_name is preserved as-is."""
        data = {
            "first_name": "Jane",
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Jane"


class TestRoundTrip:
    """Test round-trip serialize → deserialize preserves important dates."""

    def test_round_trip_with_dates(self) -> None:
        """Serialize then deserialize preserves important date data."""
        original = Contact(
            first_name="Round",
            last_name="Trip",
            important_dates=[
                ImportantDate(
                    contact_id=1,
                    date_type=ImportantDateType.BIRTHDAY,
                    precision=DatePrecision.FULL,
                    year=1990,
                    month=5,
                    day=20,
                ),
                ImportantDate(
                    contact_id=1,
                    date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
                    precision=DatePrecision.YEAR,
                    year=2015,
                ),
            ],
        )

        serialized = serialize_contact(original)
        restored = deserialize_contact(serialized)

        assert restored.important_dates is not None
        assert len(restored.important_dates) == 2

        birthday = restored.important_dates[0]
        assert birthday.date_type == ImportantDateType.BIRTHDAY
        assert birthday.precision == DatePrecision.FULL
        assert birthday.year == 1990

        anniversary = restored.important_dates[1]
        assert anniversary.date_type == ImportantDateType.MARRIAGE_ANNIVERSARY
        assert anniversary.precision == DatePrecision.YEAR
        assert anniversary.year == 2015

    def test_round_trip_with_none(self) -> None:
        """Serialize then deserialize preserves None important dates."""
        original = Contact(first_name="NoDate", important_dates=None)

        serialized = serialize_contact(original)
        restored = deserialize_contact(serialized)

        assert restored.important_dates is None
