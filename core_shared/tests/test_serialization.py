"""
Unit tests for Contact serialization with important_dates.

Tests round-trip serialize/deserialize for contact important dates,
ensuring the outbox pipeline correctly preserves date data.
"""

import pytest

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ImportantDate,
    MethodType,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.serialization import (
    ContactDeserializationError,
    deserialize_contact,
    serialize_contact,
)


class TestSerializeImportantDates:
    """Test serialization of important_dates on Contact entities."""

    def test_serialize_with_important_dates(self) -> None:
        """Contact with important_dates serializes them."""
        contact = Contact(
            user_id="user-1",
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
        contact = Contact(user_id="user-1", first_name="Test", important_dates=None)

        result = serialize_contact(contact)

        assert result["important_dates"] is None

    def test_serialize_with_empty_important_dates(self) -> None:
        """Contact with empty important_dates list serializes as empty list."""
        contact = Contact(user_id="user-1", first_name="Test", important_dates=[])

        result = serialize_contact(contact)

        assert result["important_dates"] == []


class TestDeserializeImportantDates:
    """Test deserialization of important_dates back to Contact."""

    def test_deserialize_with_important_dates(self) -> None:
        """Important dates in payload are deserialized to ImportantDate entities."""
        data = {
            "user_id": "user-1",
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
            "user_id": "user-1",
            "first_name": "Test",
            "important_dates": None,
        }

        contact = deserialize_contact(data)

        assert contact.important_dates is None

    def test_deserialize_without_important_dates_key(self) -> None:
        """Missing important_dates key in payload defaults to None."""
        data = {
            "user_id": "user-1",
            "first_name": "Test",
        }

        contact = deserialize_contact(data)

        assert contact.important_dates is None

    def test_deserialize_with_empty_important_dates(self) -> None:
        """Empty important_dates list is preserved."""
        data = {
            "user_id": "user-1",
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
            "user_id": "user-1",
            "last_name": "Doe",
            "methods": [],
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Unknown"
        assert contact.last_name == "Doe"

    def test_deserialize_with_none_first_name(self) -> None:
        """None first_name defaults to 'Unknown'."""
        data = {
            "user_id": "user-1",
            "first_name": None,
            "last_name": "Smith",
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Unknown"

    def test_deserialize_with_empty_first_name(self) -> None:
        """Empty string first_name defaults to 'Unknown'."""
        data = {
            "user_id": "user-1",
            "first_name": "   ",
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Unknown"

    def test_deserialize_with_valid_first_name_still_works(self) -> None:
        """Valid first_name is preserved as-is."""
        data = {
            "user_id": "user-1",
            "first_name": "Jane",
        }

        contact = deserialize_contact(data)

        assert contact.first_name == "Jane"


class TestRoundTrip:
    """Test round-trip serialize → deserialize preserves important dates."""

    def test_round_trip_with_dates(self) -> None:
        """Serialize then deserialize preserves important date data."""
        original = Contact(
            user_id="user-1",
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
        original = Contact(user_id="user-1", first_name="NoDate", important_dates=None)

        serialized = serialize_contact(original)
        restored = deserialize_contact(serialized)

        assert restored.important_dates is None


class TestPhotoUrlSerialization:
    """Test serialization/deserialization of photo_url field."""

    def test_serialize_with_photo_url(self) -> None:
        """Contact with photo_url serializes it."""
        contact = Contact(
            user_id="user-1",
            first_name="Test",
            photo_url="/api/contacts/42/avatar",
        )

        result = serialize_contact(contact)

        assert result["photo_url"] == "/api/contacts/42/avatar"

    def test_serialize_with_none_photo_url(self) -> None:
        """Contact with None photo_url serializes as None."""
        contact = Contact(user_id="user-1", first_name="Test")

        result = serialize_contact(contact)

        assert result["photo_url"] is None

    def test_deserialize_with_photo_url(self) -> None:
        """photo_url in payload is deserialized to Contact."""
        data = {
            "user_id": "user-1",
            "first_name": "Test",
            "photo_url": "/api/contacts/42/avatar",
        }

        contact = deserialize_contact(data)

        assert contact.photo_url == "/api/contacts/42/avatar"

    def test_deserialize_without_photo_url_key(self) -> None:
        """Missing photo_url key defaults to None."""
        data = {"user_id": "user-1", "first_name": "Test"}

        contact = deserialize_contact(data)

        assert contact.photo_url is None

    def test_round_trip_with_photo_url(self) -> None:
        """Serialize then deserialize preserves photo_url."""
        original = Contact(
            user_id="user-1",
            first_name="Round",
            last_name="Trip",
            photo_url="/api/contacts/1/avatar",
        )

        serialized = serialize_contact(original)
        restored = deserialize_contact(serialized)

        assert restored.photo_url == "/api/contacts/1/avatar"
        assert restored.first_name == "Round"
        assert restored.last_name == "Trip"


class TestArchivedSerialization:
    """``is_archived`` survives the outbox round trip on methods and addresses."""

    def test_round_trip_preserves_is_archived(self) -> None:
        original = Contact(
            user_id="user-1",
            first_name="Arch",
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="old@example.com",
                    contact_id=1,
                    is_archived=True,
                ),
                ContactMethod(
                    method_type=MethodType.PHONE,
                    value="+61 2 1234 5678",
                    contact_id=1,
                ),
            ],
            addresses=[
                ContactAddress(
                    street_line_1="1 Childhood Rd",
                    country_code="AU",
                    contact_id=1,
                    is_archived=True,
                )
            ],
        )

        restored = deserialize_contact(serialize_contact(original))

        assert restored.methods is not None
        assert [m.is_archived for m in restored.methods] == [True, False]
        assert restored.addresses is not None
        assert restored.addresses[0].is_archived is True

    def test_deserialize_without_is_archived_defaults_to_active(self) -> None:
        restored = deserialize_contact(
            {
                "user_id": "user-1",
                "first_name": "Legacy",
                "methods": [{"method_type": "email", "value": "a@example.com"}],
                "addresses": [{"street_line_1": "1 Main St", "country_code": "AU"}],
            }
        )

        assert restored.methods is not None
        assert restored.methods[0].is_archived is False
        assert restored.addresses is not None
        assert restored.addresses[0].is_archived is False


class TestOwnerSerialization:
    """The contact's owner travels through the outbox payload."""

    def test_round_trip_preserves_user_id(self) -> None:
        original = Contact(first_name="Owned", user_id="user-1")

        serialized = serialize_contact(original)
        restored = deserialize_contact(serialized)

        assert serialized["user_id"] == "user-1"
        assert restored.user_id == "user-1"

    @pytest.mark.parametrize("payload", [{}, {"user_id": None}, {"user_id": " "}])
    def test_deserialize_refuses_a_contact_without_an_owner(
        self, payload: dict[str, object]
    ) -> None:
        """Every contact has an owner; a payload that names none is malformed."""
        with pytest.raises(ContactDeserializationError, match="user_id"):
            deserialize_contact({"first_name": "Unowned", **payload})
