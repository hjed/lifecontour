"""A contact push must keep the Google data the local model cannot represent.

``update_contact`` derives ``updatePersonFields`` from the payload's keys and
Google replaces each named field wholesale (#1732). The push payload is built
from the local contact only, so without a merge every push that names
``names``, ``events`` or ``organizations`` wiped the honorifics and phonetic
names, the custom events and every other organization held in Google.
``merge_with_current_person`` folds those values back in from the person as
Google holds it now, leaving the values the local model owns as pushed.
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
        }
        payload = {"nicknames": [{"value": "Ada"}]}

        merged = merge_with_current_person(payload, current)

        assert merged == {"nicknames": [{"value": "Ada"}]}

    def test_does_not_mutate_the_payload(self) -> None:
        current = {"names": [{"honorificPrefix": "Dr"}]}
        payload = {"names": [{"givenName": "Ada"}]}

        merge_with_current_person(payload, current)

        assert payload == {"names": [{"givenName": "Ada"}]}
