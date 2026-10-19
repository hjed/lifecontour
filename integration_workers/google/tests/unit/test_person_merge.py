"""A contact push must keep the Google data the local model cannot represent.

``update_contact`` derives ``updatePersonFields`` from the payload's keys and
Google replaces each named field wholesale (#1732). The push payload is built
from the local contact only, so without a merge every push wiped what local
cannot hold: honorifics and phonetic names, custom events, other
organizations, and every entry inbound sync never imported - extra nicknames,
invalid emails and phones, addresses with no country code, a text-only birthday
(#1788). ``merge_with_current_person`` folds those values back in from the
person as Google holds it now, leaving the values the local model owns as
pushed.
"""

from typing import Any

from person_merge import merge_with_current_person

CONTACT_SOURCE = {"source": {"type": "CONTACT", "id": "c1"}}
PROFILE_SOURCE = {"source": {"type": "PROFILE", "id": "p1"}}


class TestNames:
    """Local owns given, family and middle name; the rest of the name stays."""

    def test_keeps_honorifics_and_phonetic_names(self) -> None:
        current = {
            "names": [
                {
                    "metadata": {"primary": True, **CONTACT_SOURCE},
                    "displayName": "Dr Ada Lovelace PhD",
                    "unstructuredName": "Dr Ada Lovelace PhD",
                    "givenName": "Ada",
                    "familyName": "Lovelace",
                    "honorificPrefix": "Dr",
                    "honorificSuffix": "PhD",
                    "phoneticGivenName": "ay-da",
                    "phoneticFamilyName": "luv-lace",
                }
            ]
        }
        payload = {"names": [{"givenName": "Augusta", "familyName": "King"}]}

        merged = merge_with_current_person(payload, current)

        assert merged["names"] == [
            {
                "givenName": "Augusta",
                "familyName": "King",
                "honorificPrefix": "Dr",
                "honorificSuffix": "PhD",
                "phoneticGivenName": "ay-da",
                "phoneticFamilyName": "luv-lace",
            }
        ]

    def test_middle_name_cleared_locally_is_not_restored(self) -> None:
        current = {"names": [{"givenName": "Ada", "middleName": "Augusta"}]}
        payload = {"names": [{"givenName": "Ada"}]}

        merged = merge_with_current_person(payload, current)

        assert merged["names"] == [{"givenName": "Ada"}]

    def test_reads_the_primary_name_as_inbound_sync_does(self) -> None:
        current = {
            "names": [
                {"honorificPrefix": "Mr"},
                {"metadata": {"primary": True}, "honorificPrefix": "Dr"},
            ]
        }
        payload = {"names": [{"givenName": "Ada"}]}

        merged = merge_with_current_person(payload, current)

        assert merged["names"] == [{"givenName": "Ada", "honorificPrefix": "Dr"}]

    def test_ignores_a_profile_source_name(self) -> None:
        current = {
            "names": [
                {
                    "metadata": {"primary": True, **PROFILE_SOURCE},
                    "honorificPrefix": "Dr",
                }
            ]
        }
        payload = {"names": [{"givenName": "Ada"}]}

        merged = merge_with_current_person(payload, current)

        assert merged["names"] == [{"givenName": "Ada"}]

    def test_no_current_name_leaves_the_payload_as_pushed(self) -> None:
        payload = {"names": [{"givenName": "Ada"}]}

        merged = merge_with_current_person(payload, {})

        assert merged == {"names": [{"givenName": "Ada"}]}


class TestEvents:
    """Local owns anniversaries; every other Google event is kept."""

    def test_keeps_custom_and_untyped_events(self) -> None:
        custom = {
            "metadata": CONTACT_SOURCE,
            "date": {"year": 2010, "month": 3, "day": 4},
            "type": "Graduation",
            "formattedType": "Graduation",
        }
        untyped = {"date": {"year": 0, "month": 5, "day": 6}}
        current = {"events": [custom, untyped]}
        local_anniversary = {
            "date": {"year": 2015, "month": 1, "day": 2},
            "type": "anniversary",
        }
        payload = {"events": [local_anniversary]}

        merged = merge_with_current_person(payload, current)

        assert merged["events"] == [
            local_anniversary,
            {"date": {"year": 2010, "month": 3, "day": 4}, "type": "Graduation"},
            untyped,
        ]

    def test_remote_anniversary_is_replaced_by_the_local_list(self) -> None:
        current = {
            "events": [
                {"date": {"year": 2001, "month": 1, "day": 1}, "type": "Anniversary"}
            ]
        }

        merged = merge_with_current_person({"events": []}, current)

        assert merged["events"] == []

    def test_ignores_profile_source_events(self) -> None:
        current = {
            "events": [
                {
                    "metadata": PROFILE_SOURCE,
                    "date": {"year": 2010, "month": 3, "day": 4},
                    "type": "Graduation",
                }
            ]
        }

        merged = merge_with_current_person({"events": []}, current)

        assert merged["events"] == []


class TestOrganizations:
    """Local owns the name and title of the organization inbound sync reads."""

    def test_keeps_other_orgs_and_the_owned_orgs_other_fields(self) -> None:
        current = {
            "organizations": [
                {"metadata": CONTACT_SOURCE, "name": "Old Co", "current": False},
                {
                    "metadata": CONTACT_SOURCE,
                    "name": "Analytical Engines",
                    "title": "Analyst",
                    "department": "R&D",
                    "current": True,
                    "formattedType": "Work",
                    "type": "work",
                },
            ]
        }
        payload = {
            "organizations": [{"current": True, "name": "Engines Ltd", "title": "Lead"}]
        }

        merged = merge_with_current_person(payload, current)

        assert merged["organizations"] == [
            {"name": "Old Co", "current": False},
            {
                "name": "Engines Ltd",
                "title": "Lead",
                "department": "R&D",
                "current": True,
                "type": "work",
            },
        ]

    def test_title_unset_locally_is_removed_from_the_owned_org(self) -> None:
        current = {
            "organizations": [{"name": "Engines", "title": "Analyst", "current": True}]
        }
        payload = {"organizations": [{"current": True, "name": "Engines"}]}

        merged = merge_with_current_person(payload, current)

        assert merged["organizations"] == [{"name": "Engines", "current": True}]

    def test_owned_org_falls_back_to_the_first_one(self) -> None:
        current = {
            "organizations": [
                {"name": "First", "department": "Ops"},
                {"name": "Second"},
            ]
        }
        payload = {"organizations": [{"current": True, "name": "Renamed"}]}

        merged = merge_with_current_person(payload, current)

        assert merged["organizations"] == [
            {"name": "Renamed", "department": "Ops", "current": True},
            {"name": "Second"},
        ]

    def test_profile_source_orgs_are_not_copied_into_the_contact(self) -> None:
        """Inbound reads the current profile org, so the local org takes its place."""
        current = {
            "organizations": [
                {"metadata": PROFILE_SOURCE, "name": "Profile Co", "current": True},
                {"metadata": CONTACT_SOURCE, "name": "Contact Co"},
            ]
        }
        payload = {"organizations": [{"current": True, "name": "Local Co"}]}

        merged = merge_with_current_person(payload, current)

        assert merged["organizations"] == [
            {"current": True, "name": "Local Co"},
            {"name": "Contact Co"},
        ]


class TestPayloadShape:
    """The merge never changes which fields the update replaces."""

    def test_never_adds_a_field_the_payload_does_not_carry(self) -> None:
        current: dict[str, Any] = {
            "names": [{"honorificPrefix": "Dr"}],
            "events": [{"type": "Graduation", "date": {"year": 2010}}],
            "organizations": [{"name": "Engines"}],
            "nicknames": [{"value": "AL"}],
        }
        payload = {"biographies": [{"value": "Notes", "contentType": "TEXT_PLAIN"}]}

        merged = merge_with_current_person(payload, current)

        assert merged == payload

    def test_a_field_with_no_policy_passes_through(self) -> None:
        """A gap in the registry must not fail the push; the ownership test gates it."""
        payload = {"urls": [{"value": "https://example.com"}]}

        merged = merge_with_current_person(payload, {"urls": [{"value": "x"}]})

        assert merged == payload

    def test_does_not_mutate_the_payload(self) -> None:
        current = {"names": [{"honorificPrefix": "Dr"}]}
        payload = {"names": [{"givenName": "Ada"}]}

        merge_with_current_person(payload, current)

        assert payload == {"names": [{"givenName": "Ada"}]}


class TestBirthdays:
    """Local owns a birthday inbound can read; any other one is left alone (#1788).

    Google holds one birthday per contact source, so a kept birthday cannot sit
    beside a pushed one: when local has none, the field leaves the update mask
    and Google keeps its birthday untouched. The free-text form is deprecated
    for writes, so it is never sent back.
    """

    def test_text_only_birthday_leaves_the_update_mask(self) -> None:
        current = {
            "birthdays": [{"metadata": CONTACT_SOURCE, "text": "sometime in spring"}]
        }

        merged = merge_with_current_person({"birthdays": [], "events": []}, current)

        assert merged == {"events": []}

    def test_birthday_with_no_usable_date_leaves_the_update_mask(self) -> None:
        current = {
            "birthdays": [
                {"metadata": CONTACT_SOURCE, "date": {"year": 0, "month": 0, "day": 0}}
            ]
        }

        merged = merge_with_current_person({"birthdays": []}, current)

        assert "birthdays" not in merged

    def test_local_birthday_replaces_a_text_only_one(self) -> None:
        current = {"birthdays": [{"metadata": CONTACT_SOURCE, "text": "spring"}]}
        pushed = [{"date": {"year": 1815, "month": 12, "day": 10}}]

        merged = merge_with_current_person({"birthdays": pushed}, current)

        assert merged["birthdays"] == pushed

    def test_imported_birthday_cleared_locally_is_cleared(self) -> None:
        current = {
            "birthdays": [
                {
                    "metadata": CONTACT_SOURCE,
                    "date": {"year": 1815, "month": 12, "day": 10},
                    "text": "12/10/1815",
                }
            ]
        }

        merged = merge_with_current_person({"birthdays": []}, current)

        assert merged["birthdays"] == []

    def test_profile_source_text_birthday_does_not_stop_the_clear(self) -> None:
        current = {"birthdays": [{"metadata": PROFILE_SOURCE, "text": "spring"}]}

        merged = merge_with_current_person({"birthdays": []}, current)

        assert merged["birthdays"] == []


class TestAddresses:
    """Local owns the addresses inbound imports; Google keeps the rest."""

    def test_keeps_an_address_without_a_country_code(self) -> None:
        countryless = {
            "metadata": CONTACT_SOURCE,
            "streetAddress": "1 Somewhere St",
            "city": "Sydney",
            "formattedType": "Home",
            "type": "home",
        }
        current = {"addresses": [countryless]}
        pushed = {"streetAddress": "2 Local Rd", "countryCode": "AU"}

        merged = merge_with_current_person({"addresses": [pushed]}, current)

        assert merged["addresses"] == [
            pushed,
            {"streetAddress": "1 Somewhere St", "city": "Sydney", "type": "home"},
        ]

    def test_imported_address_deleted_locally_is_not_restored(self) -> None:
        current = {
            "addresses": [
                {
                    "metadata": CONTACT_SOURCE,
                    "streetAddress": "1 Somewhere St",
                    "countryCode": "AU",
                }
            ]
        }

        merged = merge_with_current_person({"addresses": []}, current)

        assert merged["addresses"] == []


class TestContactMethods:
    """Local owns the emails and phones inbound imports; invalid ones stay."""

    def test_keeps_an_email_inbound_rejects(self) -> None:
        current = {
            "emailAddresses": [
                {"metadata": CONTACT_SOURCE, "value": "not an email"},
                {"metadata": CONTACT_SOURCE, "value": "ada@example.com"},
            ]
        }

        merged = merge_with_current_person({"emailAddresses": []}, current)

        assert merged["emailAddresses"] == [{"value": "not an email"}]

    def test_keeps_a_phone_inbound_rejects(self) -> None:
        current = {
            "phoneNumbers": [
                {"metadata": CONTACT_SOURCE, "value": "call reception"},
                {
                    "metadata": CONTACT_SOURCE,
                    "value": "(02) 9999 0000",
                    "canonicalForm": "+61299990000",
                },
            ]
        }
        pushed = [{"value": "+61400000000"}]

        merged = merge_with_current_person({"phoneNumbers": pushed}, current)

        assert merged["phoneNumbers"] == [*pushed, {"value": "call reception"}]

    def test_a_malformed_entry_is_kept_not_raised(self) -> None:
        """Inbound cannot read an email with no value, so local never owned it."""
        current = {"emailAddresses": [{"metadata": CONTACT_SOURCE, "type": "work"}]}

        merged = merge_with_current_person({"emailAddresses": []}, current)

        assert merged["emailAddresses"] == [{"type": "work"}]

    def test_profile_source_invalid_email_is_not_copied(self) -> None:
        current = {"emailAddresses": [{"metadata": PROFILE_SOURCE, "value": "nope"}]}

        merged = merge_with_current_person({"emailAddresses": []}, current)

        assert merged["emailAddresses"] == []


class TestNicknames:
    """Local owns the one nickname inbound reads; Google keeps the others."""

    def test_keeps_every_nickname_but_the_one_inbound_reads(self) -> None:
        current = {
            "nicknames": [
                {"metadata": CONTACT_SOURCE, "value": "Addie"},
                {"metadata": {"primary": True, **CONTACT_SOURCE}, "value": "Ada"},
                {"metadata": CONTACT_SOURCE, "value": "AL", "type": "INITIALS"},
            ]
        }

        merged = merge_with_current_person(
            {"nicknames": [{"value": "Countess"}]}, current
        )

        assert merged["nicknames"] == [
            {"value": "Countess"},
            {"value": "Addie"},
            {"value": "AL", "type": "INITIALS"},
        ]

    def test_nickname_cleared_locally_clears_them_all(self) -> None:
        """A survivor would be the nickname inbound reads next, undoing the clear."""
        current = {
            "nicknames": [
                {"metadata": CONTACT_SOURCE, "value": "Ada"},
                {"metadata": CONTACT_SOURCE, "value": "AL"},
            ]
        }

        merged = merge_with_current_person({"nicknames": []}, current)

        assert merged["nicknames"] == []

    def test_a_second_push_replaces_the_same_nickname(self) -> None:
        """The pushed nickname leads, so inbound and the next push both read it."""
        current = {
            "nicknames": [
                {"metadata": {"primary": True, **CONTACT_SOURCE}, "value": "Ada"},
                {"metadata": CONTACT_SOURCE, "value": "AL"},
            ]
        }
        payload = {"nicknames": [{"value": "Countess"}]}
        first = merge_with_current_person(payload, current)

        second = merge_with_current_person(payload, first)

        assert second["nicknames"] == [{"value": "Countess"}, {"value": "AL"}]
