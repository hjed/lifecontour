"""Keys of the Google entries a sync agreed on (#1861).

The pull keys the person it read; the push keys the person Google returns and
the one it merges into. All three must agree on an entry however Google labels,
orders or formats it, so a key covers only the value inbound imports.
"""

from typing import Any

import pytest

from api_models import GooglePerson
from synced_entries import (
    BASE_FIELDS,
    raw_entry_key,
    raw_synced_entries,
    synced_entries_of,
)

pytestmark = pytest.mark.unit

_CONTACT = {"source": {"type": "CONTACT", "id": "c1"}}


def _person(**fields: Any) -> GooglePerson:
    return GooglePerson.model_validate({"resourceName": "people/c1", **fields})


class TestRawEntryKey:
    def test_an_email_keys_by_value_alone(self) -> None:
        pulled = {
            "metadata": {"primary": True, **_CONTACT},
            "value": "Ada@Example.com",
            "type": "work",
            "formattedType": "Work",
        }
        pushed = {"value": "ada@example.com", "type": "home"}

        assert raw_entry_key("emailAddresses", pulled, None) == raw_entry_key(
            "emailAddresses", pushed, None
        )

    def test_a_phone_keys_by_its_canonical_form(self) -> None:
        pulled = {
            "value": "0412 345 678",
            "canonicalForm": "+61412345678",
            "formattedType": "Mobile",
        }
        returned = {"value": "+61 412 345 678", "canonicalForm": "+61412345678"}

        assert raw_entry_key("phoneNumbers", pulled, None) == raw_entry_key(
            "phoneNumbers", returned, None
        )

    def test_a_phone_typed_nationally_keys_as_its_canonical_form(self) -> None:
        """A local phone is pushed as typed; Google answers with it canonical."""
        typed = {"value": "0412 345 678"}
        canonical = {"value": "0412 345 678", "canonicalForm": "+61412345678"}

        assert raw_entry_key("phoneNumbers", typed, None) == raw_entry_key(
            "phoneNumbers", canonical, None
        )

    def test_different_values_key_differently(self) -> None:
        assert raw_entry_key(
            "emailAddresses", {"value": "ada@example.com"}, None
        ) != raw_entry_key("emailAddresses", {"value": "kiri@example.com"}, None)

    def test_an_address_keys_by_its_parts_not_its_label(self) -> None:
        home = {"streetAddress": "1 Queen St", "city": "Auckland", "countryCode": "NZ"}
        work = {**home, "type": "work", "formattedType": "Work"}

        assert raw_entry_key("addresses", home, None) == raw_entry_key(
            "addresses", work, None
        )

    def test_an_address_with_a_second_line_keys_as_the_push_folds_it(self) -> None:
        """Pulled with ``extendedAddress``; pushed with both lines in the street."""
        pulled = {
            "streetAddress": "1 Queen St",
            "extendedAddress": "Unit 2",
            "countryCode": "NZ",
        }
        pushed = {"streetAddress": "1 Queen St\nUnit 2", "countryCode": "NZ"}

        assert raw_entry_key("addresses", pulled, None) == raw_entry_key(
            "addresses", pushed, None
        )

    def test_an_address_whose_lines_are_long_together_still_keys(self) -> None:
        """Each line is valid alone; keying them as one must not revalidate."""
        address = {
            "streetAddress": "1" * 200,
            "extendedAddress": "2" * 100,
            "countryCode": "NZ",
        }

        assert raw_entry_key("addresses", address, None) is not None

    def test_a_countryless_address_keys_with_the_fallback_it_was_read_with(
        self,
    ) -> None:
        countryless = {"streetAddress": "1 Queen St", "city": "Auckland"}
        with_country = {**countryless, "countryCode": "NZ"}

        assert raw_entry_key("addresses", countryless, "NZ") == raw_entry_key(
            "addresses", with_country, None
        )
        assert raw_entry_key("addresses", countryless, "AU") != raw_entry_key(
            "addresses", countryless, "NZ"
        )

    def test_a_birthday_keys_by_its_date(self) -> None:
        first = {"date": {"year": 1990, "month": 3, "day": 4}, "text": "4 March"}
        second = {"metadata": _CONTACT, "date": {"year": 1990, "month": 3, "day": 4}}

        assert raw_entry_key("birthdays", first, None) == raw_entry_key(
            "birthdays", second, None
        )

    @pytest.mark.parametrize(
        ("field", "entry"),
        [
            ("emailAddresses", {"value": "not an email"}),
            ("emailAddresses", {"type": "home"}),
            ("phoneNumbers", {"value": ""}),
            ("addresses", {"streetAddress": "2 Nowhere Rd", "city": "Leeds"}),
            ("birthdays", {"text": "sometime in December"}),
        ],
    )
    def test_an_entry_inbound_never_imports_has_no_key(
        self, field: Any, entry: dict[str, Any]
    ) -> None:
        assert raw_entry_key(field, entry, None) is None


class TestSyncedEntriesOf:
    def test_keys_every_imported_entry_per_field(self) -> None:
        email = {"value": "ada@example.com", "formattedType": "Home"}
        phone = {"value": "+61412345678", "canonicalForm": "+61412345678"}
        address = {"streetAddress": "1 Queen St", "countryCode": "NZ"}
        birthday = {"date": {"year": 1990, "month": 3, "day": 4}}
        person = _person(
            emailAddresses=[email, {"value": "not an email"}],
            phoneNumbers=[phone],
            addresses=[address, {"streetAddress": "2 Nowhere Rd"}],
            birthdays=[birthday, {"text": "December"}],
        )

        assert synced_entries_of(person, None) == {
            "emailAddresses": {raw_entry_key("emailAddresses", email, None)},
            "phoneNumbers": {raw_entry_key("phoneNumbers", phone, None)},
            "addresses": {raw_entry_key("addresses", address, None)},
            "birthdays": {raw_entry_key("birthdays", birthday, None)},
        }

    def test_records_every_field_even_when_empty(self) -> None:
        """An empty field is a statement: the sync agreed it held nothing."""
        assert synced_entries_of(_person(), None) == {
            field: frozenset() for field in BASE_FIELDS
        }

    def test_keys_a_countryless_address_with_the_fallback(self) -> None:
        address = {"streetAddress": "1 Queen St", "city": "Auckland"}

        synced = synced_entries_of(_person(addresses=[address]), "NZ")

        assert synced["addresses"] == {raw_entry_key("addresses", address, "NZ")}

    def test_a_raw_person_keys_as_the_parsed_one(self) -> None:
        """The push keys Google's raw response; the pull keys the parsed person."""
        raw = {
            "resourceName": "people/c1",
            "emailAddresses": [{"value": "ada@example.com", "formattedType": "Home"}],
            "phoneNumbers": [
                {"value": "0412 345 678", "canonicalForm": "+61412345678"}
            ],
            "addresses": [{"streetAddress": "1 Queen St"}],
            "birthdays": [{"date": {"month": 3, "day": 4}}],
        }

        assert raw_synced_entries(raw, "NZ") == synced_entries_of(
            GooglePerson.model_validate(raw), "NZ"
        )
