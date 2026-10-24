"""A push merges three ways against the synced base (#1861).

The base is what the last sync agreed both sides held. Without it the push
owned every entry inbound *could* import, so an email, phone, address or
birthday added in Google since the last pull was deleted by the next push of a
local edit. With it:

* an entry Google gained since the base is kept, and the next pull imports it;
* an entry in the base the contact no longer holds was deleted locally: dropped;
* an entry in the base Google no longer holds was deleted or edited there, and
  the unchanged local copy is not pushed back over it;
* an entry both sides hold is sent once.
"""

from typing import Any

import pytest

from person_merge import PushMerge, merge_for_push, resolve_synced_base
from synced_entries import BaseField, raw_entry_key

pytestmark = pytest.mark.unit

CONTACT_SOURCE = {"source": {"type": "CONTACT", "id": "c1"}}

ADA = {"value": "ada@example.com"}
NEW = {"value": "new@example.com"}
OLD = {"value": "old@example.com"}


def _google(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"metadata": CONTACT_SOURCE, **entry} for entry in entries]


def _keys(
    field: BaseField, *entries: dict[str, Any], fallback: str | None = None
) -> frozenset[str]:
    return frozenset(
        key
        for entry in entries
        if (key := raw_entry_key(field, entry, fallback)) is not None
    )


def _merge(
    field: BaseField,
    pushed: list[dict[str, Any]],
    google: list[dict[str, Any]],
    base: list[dict[str, Any]],
    *,
    fallback: str | None = None,
) -> PushMerge:
    return merge_for_push(
        {field: pushed},
        {field: _google(*google)},
        synced_base={field: _keys(field, *base, fallback=fallback)},
        address_fallback_country=fallback,
    )


class TestEmails:
    def test_an_email_added_in_google_since_the_base_is_kept(self) -> None:
        merged = _merge("emailAddresses", [ADA], google=[ADA, NEW], base=[ADA])

        assert merged.payload["emailAddresses"] == [ADA, NEW]
        assert merged.kept["emailAddresses"] == _keys("emailAddresses", NEW)
        assert merged.pending_import is True

    def test_an_email_deleted_locally_is_dropped(self) -> None:
        merged = _merge("emailAddresses", [ADA], google=[ADA, OLD], base=[ADA, OLD])

        assert merged.payload["emailAddresses"] == [ADA]
        assert merged.pending_import is False

    def test_an_email_deleted_in_google_is_not_pushed_back(self) -> None:
        merged = _merge("emailAddresses", [ADA, OLD], google=[ADA], base=[ADA, OLD])

        assert merged.payload["emailAddresses"] == [ADA]
        assert merged.pending_import is True

    def test_an_email_edited_in_google_replaces_the_unchanged_local_one(
        self,
    ) -> None:
        merged = _merge("emailAddresses", [OLD], google=[NEW], base=[OLD])

        assert merged.payload["emailAddresses"] == [NEW]
        assert merged.pending_import is True

    def test_an_email_added_on_both_sides_is_sent_once(self) -> None:
        merged = _merge("emailAddresses", [ADA, NEW], google=[ADA, NEW], base=[ADA])

        assert merged.payload["emailAddresses"] == [ADA, NEW]
        assert merged.pending_import is False

    def test_an_email_added_locally_is_pushed(self) -> None:
        merged = _merge("emailAddresses", [ADA, NEW], google=[ADA], base=[ADA])

        assert merged.payload["emailAddresses"] == [ADA, NEW]
        assert merged.pending_import is False

    def test_an_email_inbound_rejects_is_kept_without_a_pending_import(
        self,
    ) -> None:
        """Never imported, so the next pull has nothing to import from it."""
        invalid = {"value": "not an email"}

        merged = _merge("emailAddresses", [ADA], google=[ADA, invalid], base=[ADA])

        assert merged.payload["emailAddresses"] == [ADA, invalid]
        assert merged.pending_import is False

    def test_a_profile_email_is_never_kept(self) -> None:
        merged = merge_for_push(
            {"emailAddresses": [ADA]},
            {"emailAddresses": [{"metadata": {"source": {"type": "PROFILE"}}, **NEW}]},
            synced_base={"emailAddresses": frozenset()},
        )

        assert merged.payload["emailAddresses"] == [ADA]
        assert merged.pending_import is False


class TestPhones:
    def test_a_phone_added_in_google_since_the_base_is_kept(self) -> None:
        held = {"value": "+61400000000"}
        added = {"value": "0412 345 678", "canonicalForm": "+61412345678"}

        merged = _merge("phoneNumbers", [held], google=[held, added], base=[held])

        assert merged.payload["phoneNumbers"] == [held, added]
        assert merged.pending_import is True


class TestAddresses:
    def test_an_address_added_in_google_since_the_base_is_kept(self) -> None:
        held = {"streetAddress": "1 Main St", "countryCode": "AU"}
        added = {"streetAddress": "2 New Rd", "countryCode": "AU"}

        merged = _merge("addresses", [held], google=[held, added], base=[held])

        assert merged.payload["addresses"] == [held, added]

    def test_a_countryless_address_added_since_a_pull_with_a_fallback_is_kept(
        self,
    ) -> None:
        """The #1859 review finding: the recorded fallback alone owned it."""
        imported = {"streetAddress": "1 Queen St"}
        added = {"streetAddress": "9 Added Ave"}
        pushed = {"streetAddress": "1 Queen St", "countryCode": "NZ"}

        merged = _merge(
            "addresses",
            [pushed],
            google=[imported, added],
            base=[imported],
            fallback="NZ",
        )

        assert merged.payload["addresses"] == [pushed, added]
        assert merged.pending_import is True

    def test_a_countryless_address_the_pull_imported_is_replaced(self) -> None:
        imported = {"streetAddress": "1 Queen St"}
        pushed = {"streetAddress": "1 Queen St", "countryCode": "NZ"}

        merged = _merge(
            "addresses", [pushed], google=[imported], base=[imported], fallback="NZ"
        )

        assert merged.payload["addresses"] == [pushed]
        assert merged.pending_import is False


class TestBirthdays:
    BORN = {"date": {"year": 1815, "month": 12, "day": 10}}
    FIXED = {"date": {"year": 1815, "month": 12, "day": 11}}

    def test_a_birthday_added_in_google_is_left_alone(self) -> None:
        merged = _merge("birthdays", [], google=[self.BORN], base=[])

        assert "birthdays" not in merged.payload
        assert merged.pending_import is True

    def test_a_birthday_edited_in_google_wins_over_the_unchanged_local_one(
        self,
    ) -> None:
        merged = _merge("birthdays", [self.BORN], google=[self.FIXED], base=[self.BORN])

        assert "birthdays" not in merged.payload
        assert merged.pending_import is True

    def test_a_birthday_edited_locally_is_pushed(self) -> None:
        merged = _merge("birthdays", [self.FIXED], google=[self.BORN], base=[self.BORN])

        assert merged.payload["birthdays"] == [self.FIXED]
        assert merged.pending_import is False

    def test_a_birthday_cleared_locally_is_cleared(self) -> None:
        merged = _merge("birthdays", [], google=[self.BORN], base=[self.BORN])

        assert merged.payload["birthdays"] == []


class TestMergedFields:
    def test_names_the_base_fields_the_update_sends(self) -> None:
        merged = merge_for_push(
            {"emailAddresses": [ADA], "birthdays": [], "names": []},
            {"birthdays": _google({"text": "spring"})},
            synced_base={},
        )

        assert merged.merged_fields == {"emailAddresses"}


class TestResolveSyncedBase:
    CURRENT = {"etag": "e2", "emailAddresses": _google(ADA)}

    def test_a_recorded_base_is_used_as_recorded(self) -> None:
        recorded = {"emailAddresses": frozenset({"k"})}

        assert (
            resolve_synced_base(recorded, self.CURRENT, synced_version="e2") is recorded
        )

    def test_without_a_record_an_unchanged_person_is_its_own_base(self) -> None:
        base = resolve_synced_base(None, self.CURRENT, synced_version="e2")

        assert base["emailAddresses"] == _keys("emailAddresses", ADA)

    def test_without_a_record_a_changed_person_has_an_empty_base(self) -> None:
        """Nothing tells an addition from a deletion, so keep everything."""
        assert resolve_synced_base(None, self.CURRENT, synced_version="e1") == {}
