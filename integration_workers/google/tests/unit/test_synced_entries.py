"""Keys of the Google entries a sync agreed on (#1861).

The pull keys the person it read; the push keys the person Google returns and
the one it merges into. All three must agree on an entry however Google labels,
orders or formats it, so a key covers only the value inbound imports.
"""

from typing import Any

import pytest
from core_shared.models.contacts.sync_scope import ContactSyncField

from api_models import GooglePerson
from synced_entries import (
    BASE_FIELDS,
    LIST_BASES,
    empty_at_source,
    person_source_versions,
    raw_entry_keys,
    raw_synced_entries,
    synced_entries_of,
)
from transformer import GOOGLE_CONTACT_SYNC_SCOPE

pytestmark = pytest.mark.unit

_CONTACT = {"source": {"type": "CONTACT", "id": "c1"}}


def _person(**fields: Any) -> GooglePerson:
    return GooglePerson.model_validate({"resourceName": "people/c1", **fields})


def _same_entry(field: Any, first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Two raw entries are one entry when any of their keys match."""
    return bool(
        raw_entry_keys(field, first, None) & raw_entry_keys(field, second, None)
    )


class TestRawEntryKeys:
    def test_an_email_keys_by_value_alone(self) -> None:
        pulled = {
            "metadata": {"primary": True, **_CONTACT},
            "value": "Ada@Example.com",
            "type": "work",
            "formattedType": "Work",
        }
        pushed = {"value": "ada@example.com", "type": "home"}

        assert raw_entry_keys("emailAddresses", pulled, None) == raw_entry_keys(
            "emailAddresses", pushed, None
        )

    def test_a_phone_matches_however_google_formats_it(self) -> None:
        pulled = {
            "value": "0412 345 678",
            "canonicalForm": "+61412345678",
            "formattedType": "Mobile",
        }
        returned = {"value": "+61 412 345 678", "canonicalForm": "+61412345678"}

        assert _same_entry("phoneNumbers", pulled, returned)

    def test_a_phone_typed_nationally_matches_google_s_copy_of_it(self) -> None:
        """A local phone is pushed as typed; Google answers with it canonical."""
        typed = {"value": "0412 345 678"}
        canonical = {"value": "0412 345 678", "canonicalForm": "+61412345678"}

        assert _same_entry("phoneNumbers", typed, canonical)

    def test_a_phone_typed_with_its_country_prefix_matches_its_canonical_form(
        self,
    ) -> None:
        typed = {"value": "1 (202) 555-0123"}
        canonical = {"value": "1 (202) 555-0123", "canonicalForm": "+12025550123"}

        assert _same_entry("phoneNumbers", typed, canonical)

    def test_the_same_number_in_two_countries_is_two_phones(self) -> None:
        assert not _same_entry(
            "phoneNumbers",
            {"value": "+1 202 555 0123", "canonicalForm": "+12025550123"},
            {"value": "+44 20 2555 0123", "canonicalForm": "+442025550123"},
        )

    def test_a_national_number_never_matches_another_country_s_international_one(
        self,
    ) -> None:
        """US "(656) 500-1234" and Singapore "+65 6500 1234" share their digits."""
        assert not _same_entry(
            "phoneNumbers",
            {"value": "(656) 500-1234", "canonicalForm": "+16565001234"},
            {"value": "+65 6500 1234", "canonicalForm": "+6565001234"},
        )

    def test_different_values_key_differently(self) -> None:
        assert not _same_entry(
            "emailAddresses",
            {"value": "ada@example.com"},
            {"value": "kiri@example.com"},
        )

    def test_an_address_keys_by_its_parts_not_its_label(self) -> None:
        home = {"streetAddress": "1 Queen St", "city": "Auckland", "countryCode": "NZ"}
        work = {**home, "type": "work", "formattedType": "Work"}

        assert raw_entry_keys("addresses", home, None) == raw_entry_keys(
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

        assert raw_entry_keys("addresses", pulled, None) == raw_entry_keys(
            "addresses", pushed, None
        )

    def test_an_address_whose_lines_are_long_together_still_keys(self) -> None:
        """Each line is valid alone; keying them as one must not revalidate."""
        address = {
            "streetAddress": "1" * 200,
            "extendedAddress": "2" * 100,
            "countryCode": "NZ",
        }

        assert raw_entry_keys("addresses", address, None)

    def test_a_countryless_address_keys_with_the_fallback_it_was_read_with(
        self,
    ) -> None:
        countryless = {"streetAddress": "1 Queen St", "city": "Auckland"}
        with_country = {**countryless, "countryCode": "NZ"}

        assert raw_entry_keys("addresses", countryless, "NZ") == raw_entry_keys(
            "addresses", with_country, None
        )
        assert raw_entry_keys("addresses", countryless, "AU") != raw_entry_keys(
            "addresses", countryless, "NZ"
        )

    def test_a_birthday_keys_by_its_date(self) -> None:
        first = {"date": {"year": 1990, "month": 3, "day": 4}, "text": "4 March"}
        second = {"metadata": _CONTACT, "date": {"year": 1990, "month": 3, "day": 4}}

        assert raw_entry_keys("birthdays", first, None) == raw_entry_keys(
            "birthdays", second, None
        )

    def test_an_organization_keys_by_company_and_title_as_inbound_strips_them(
        self,
    ) -> None:
        held = {"name": " Acme ", "title": "Engineer", "department": "R&D"}
        relabelled = {"metadata": _CONTACT, "name": "Acme", "title": "Engineer "}

        assert raw_entry_keys("organizations", held, None) == raw_entry_keys(
            "organizations", relabelled, None
        )
        assert raw_entry_keys("organizations", held, None) != raw_entry_keys(
            "organizations", {"name": "Acme"}, None
        )

    def test_a_biography_keys_by_its_text_case_and_all(self) -> None:
        """A case-only edit in Google is an edit: a local clear must not delete it."""
        first = {"value": "Met at the conference\n", "contentType": "TEXT_PLAIN"}
        second = {"metadata": _CONTACT, "value": "Met at the conference"}

        assert raw_entry_keys("biographies", first, None) == raw_entry_keys(
            "biographies", second, None
        )
        assert raw_entry_keys("biographies", first, None) != raw_entry_keys(
            "biographies", {"value": "met at the conference"}, None
        )

    def test_a_nickname_keys_by_its_text_as_inbound_strips_it(self) -> None:
        first = {"value": " Addy "}
        second = {"metadata": {**_CONTACT, "primary": True}, "value": "Addy"}

        assert raw_entry_keys("nicknames", first, None) == raw_entry_keys(
            "nicknames", second, None
        )
        assert raw_entry_keys("nicknames", first, None) != raw_entry_keys(
            "nicknames", {"value": "addy"}, None
        )

    def test_an_anniversary_keys_by_its_date_not_its_label(self) -> None:
        first = {"type": "anniversary", "date": {"year": 2001, "month": 6, "day": 2}}
        second = {
            "metadata": _CONTACT,
            "type": "Anniversary",
            "formattedType": "Anniversary",
            "date": {"year": 2001, "month": 6, "day": 2},
        }

        assert raw_entry_keys("events", first, None) == raw_entry_keys(
            "events", second, None
        )
        assert raw_entry_keys("events", first, None) != raw_entry_keys(
            "events", {**first, "date": {"month": 6, "day": 2}}, None
        )

    @pytest.mark.parametrize(
        ("field", "entry"),
        [
            ("nicknames", {"value": "  "}),
            ("events", {"type": "graduation", "date": {"year": 1999, "month": 1}}),
            ("events", {"date": {"year": 2001, "month": 6, "day": 2}}),
            ("events", {"type": "anniversary"}),
            ("emailAddresses", {"value": "not an email"}),
            ("emailAddresses", {"type": "home"}),
            ("phoneNumbers", {"value": ""}),
            ("addresses", {"streetAddress": "2 Nowhere Rd", "city": "Leeds"}),
            ("birthdays", {"text": "sometime in December"}),
            ("organizations", {"department": "Research", "current": True}),
            ("organizations", {"name": "  ", "title": ""}),
            ("biographies", {"value": "   "}),
        ],
    )
    def test_an_entry_inbound_never_imports_has_no_key(
        self, field: Any, entry: dict[str, Any]
    ) -> None:
        assert raw_entry_keys(field, entry, None) == frozenset()


class TestSyncedEntriesOf:
    def test_keys_every_imported_entry_per_field(self) -> None:
        email = {"value": "ada@example.com", "formattedType": "Home"}
        phone = {"value": "+61412345678", "canonicalForm": "+61412345678"}
        address = {"streetAddress": "1 Queen St", "countryCode": "NZ"}
        birthday = {"date": {"year": 1990, "month": 3, "day": 4}}
        organization = {"name": "Acme", "title": "Engineer", "current": True}
        biographies = [{"value": "Met at the conference"}, {"value": "Likes tea"}]
        nickname = {"value": "Addy"}
        anniversary = {"type": "anniversary", "date": {"year": 2001, "month": 6}}
        person = _person(
            nicknames=[nickname, {"value": "Ace"}],
            events=[anniversary, {"type": "graduation", "date": {"year": 1999}}],
            emailAddresses=[email, {"value": "not an email"}],
            phoneNumbers=[phone],
            addresses=[address, {"streetAddress": "2 Nowhere Rd"}],
            birthdays=[birthday, {"text": "December"}],
            organizations=[organization],
            biographies=[*biographies, {"value": " "}],
        )

        assert synced_entries_of(person, None) == {
            "emailAddresses": raw_entry_keys("emailAddresses", email, None),
            "phoneNumbers": raw_entry_keys("phoneNumbers", phone, None),
            "addresses": raw_entry_keys("addresses", address, None),
            "birthdays": raw_entry_keys("birthdays", birthday, None),
            "organizations": raw_entry_keys("organizations", organization, None),
            "biographies": frozenset().union(
                *(raw_entry_keys("biographies", bio, None) for bio in biographies)
            ),
            "nicknames": raw_entry_keys("nicknames", nickname, None),
            "events": raw_entry_keys("events", anniversary, None),
        }

    @pytest.mark.parametrize(
        ("nicknames", "imported"),
        [
            ([{"value": "Addy"}, {"value": "Ace"}], 0),
            ([{"value": " "}, {"value": "Ace"}], 1),
            ([{"value": "Addy"}, {"value": "Ace", "metadata": {"primary": True}}], 1),
        ],
    )
    def test_keys_only_the_nickname_inbound_imports(
        self, nicknames: list[dict[str, Any]], imported: int
    ) -> None:
        """Inbound reads one nickname, primary else the first with a value."""
        expected = raw_entry_keys("nicknames", nicknames[imported], None)
        raw = {"resourceName": "people/c1", "nicknames": nicknames}

        assert synced_entries_of(_person(nicknames=nicknames), None)["nicknames"] == (
            expected
        )
        assert raw_synced_entries(raw, None)["nicknames"] == expected

    @pytest.mark.parametrize(
        ("organizations", "imported"),
        [
            ([{"name": "Acme"}, {"name": "Globex", "current": True}], 1),
            ([{"name": "Acme"}, {"name": "Globex"}], 0),
            ([{"name": "Acme", "current": False}, {"name": "Globex"}], 0),
        ],
    )
    def test_keys_only_the_organization_inbound_imports(
        self, organizations: list[dict[str, Any]], imported: int
    ) -> None:
        """Inbound reads one organization, current else first, into the company."""
        expected = raw_entry_keys("organizations", organizations[imported], None)
        raw = {"resourceName": "people/c1", "organizations": organizations}

        assert (
            synced_entries_of(_person(organizations=organizations), None)[
                "organizations"
            ]
            == expected
        )
        assert raw_synced_entries(raw, None)["organizations"] == expected

    def test_records_every_field_even_when_empty(self) -> None:
        """An empty field is a statement: the sync agreed it held nothing."""
        assert synced_entries_of(_person(), None) == {
            field: frozenset() for field in BASE_FIELDS
        }

    def test_keys_a_countryless_address_with_the_fallback(self) -> None:
        address = {"streetAddress": "1 Queen St", "city": "Auckland"}

        synced = synced_entries_of(_person(addresses=[address]), "NZ")

        assert synced["addresses"] == raw_entry_keys("addresses", address, "NZ")

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
            "organizations": [{"name": "Acme"}, {"name": "Globex", "current": True}],
            "biographies": [{"value": "Likes tea", "contentType": "TEXT_PLAIN"}],
            "nicknames": [{"value": "Addy"}, {"value": "Ace"}],
            "events": [
                {"type": "Anniversary", "date": {"year": 2001, "month": 6, "day": 2}}
            ],
        }

        assert raw_synced_entries(raw, "NZ") == synced_entries_of(
            GooglePerson.model_validate(raw), "NZ"
        )


class TestEmptyAtSource:
    """The lists Google holds no entries in, for the backend to clear (#1909)."""

    def test_a_person_with_no_addresses_or_notes_reports_them_empty(self) -> None:
        assert empty_at_source(_person()) == {
            ContactSyncField.ADDRESSES: "addresses",
            ContactSyncField.NOTES: "biographies",
        }

    def test_a_person_with_a_biography_holds_notes(self) -> None:
        """Google deleting the last note reaches the contact (#1925)."""
        person = _person(addresses=[{"streetAddress": "1 Nowhere Rd"}])
        noted = _person(
            addresses=[{"streetAddress": "1 Nowhere Rd"}],
            biographies=[{"value": "Likes tea"}],
        )

        assert empty_at_source(person) == {ContactSyncField.NOTES: "biographies"}
        assert empty_at_source(noted) == {}

    def test_an_address_inbound_cannot_import_still_counts_as_held(self) -> None:
        """Google still holds it, so the contact's addresses are not cleared."""
        person = _person(addresses=[{"streetAddress": "1 Nowhere Rd"}])

        assert synced_entries_of(person, None)["addresses"] == frozenset()
        assert ContactSyncField.ADDRESSES not in empty_at_source(person)

    def test_every_list_base_is_a_base_field_of_an_owned_list(self) -> None:
        assert set(LIST_BASES.values()) <= set(BASE_FIELDS)
        assert set(LIST_BASES) <= GOOGLE_CONTACT_SYNC_SCOPE.fields


class TestPersonSourceVersions:
    """The version time of each source, so a push can order a pull (#1938)."""

    def test_reads_each_sources_update_time(self) -> None:
        metadata = {
            "sources": [
                {"type": "CONTACT", "id": "c1", "etag": "x", "updateTime": "t1"},
                {"type": "PROFILE", "id": "p1", "updateTime": "t2"},
            ]
        }
        assert person_source_versions(metadata) == {
            "CONTACT/c1": "t1",
            "PROFILE/p1": "t2",
        }

    @pytest.mark.parametrize(
        "metadata",
        [
            {},
            {"sources": None},
            {"sources": "CONTACT"},
            {"sources": [{"type": "CONTACT", "id": "c1"}]},
            {"sources": [{"type": "CONTACT", "updateTime": "t1"}]},
            {"sources": [{"id": "c1", "updateTime": "t1"}]},
            {"sources": ["CONTACT"]},
        ],
    )
    def test_a_source_without_a_readable_version_records_none(
        self, metadata: dict[str, Any]
    ) -> None:
        """One source missing its version leaves the person unordered."""
        assert person_source_versions(metadata) == {}

    def test_one_unreadable_source_records_none_for_the_person(self) -> None:
        metadata = {
            "sources": [
                {"type": "CONTACT", "id": "c1", "updateTime": "t1"},
                {"type": "PROFILE", "id": "p1"},
            ]
        }
        assert person_source_versions(metadata) == {}
