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
from synced_entries import BASE_FIELDS, BaseField, raw_entry_keys

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
    return frozenset().union(
        *(raw_entry_keys(field, entry, fallback) for entry in entries)
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

    def test_a_profile_email_is_never_copied_into_the_contact(self) -> None:
        """Inbound imports a profile's email, so the pull is still owed it."""
        merged = merge_for_push(
            {"emailAddresses": [ADA]},
            {"emailAddresses": [{"metadata": {"source": {"type": "PROFILE"}}, **NEW}]},
            synced_base={"emailAddresses": frozenset()},
        )

        assert merged.payload["emailAddresses"] == [ADA]
        assert merged.pending_import is True


class TestPhones:
    def test_a_phone_added_in_google_since_the_base_is_kept(self) -> None:
        held = {"value": "+61400000000"}
        added = {"value": "0412 345 678", "canonicalForm": "+61412345678"}

        merged = _merge("phoneNumbers", [held], google=[held, added], base=[held])

        assert merged.payload["phoneNumbers"] == [held, added]
        assert merged.pending_import is True

    def test_a_phone_typed_nationally_and_deleted_in_google_is_not_pushed_back(
        self,
    ) -> None:
        canonical = {"value": "0412 345 678", "canonicalForm": "+61412345678"}

        merged = _merge(
            "phoneNumbers", [{"value": "0412 345 678"}], google=[], base=[canonical]
        )

        assert merged.payload["phoneNumbers"] == []
        assert merged.suppressed["phoneNumbers"] == _keys(
            "phoneNumbers", {"value": "0412 345 678"}
        )
        assert merged.pending_import is True

    def test_a_phone_typed_with_its_country_prefix_and_deleted_in_google_stays_gone(
        self,
    ) -> None:
        typed = {"value": "1 (202) 555-0123"}
        canonical = {**typed, "canonicalForm": "+12025550123"}

        merged = _merge("phoneNumbers", [typed], google=[], base=[canonical])

        assert merged.payload["phoneNumbers"] == []

    def test_a_number_added_in_google_in_another_country_is_kept(self) -> None:
        """Same national number, different country: a different phone."""
        held = {"value": "+1 202 555 0123", "canonicalForm": "+12025550123"}
        added = {"value": "+44 20 2555 0123", "canonicalForm": "+442025550123"}

        merged = _merge("phoneNumbers", [held], google=[held, added], base=[held])

        assert merged.payload["phoneNumbers"] == [held, added]

    def test_a_phone_added_on_both_sides_typed_differently_is_sent_once(
        self,
    ) -> None:
        local = {"value": "+61412345678"}
        google = {"value": "0412 345 678", "canonicalForm": "+61412345678"}

        merged = _merge("phoneNumbers", [local], google=[google], base=[])

        assert merged.payload["phoneNumbers"] == [local]
        assert merged.pending_import is False


class TestHeldBack:
    def test_reports_the_local_entries_it_held_back(self) -> None:
        """Still local's, so the next base holds them: a second push before the
        pull must hold them back again, not push them as new."""
        merged = _merge("emailAddresses", [ADA, OLD], google=[ADA], base=[ADA, OLD])

        assert merged.suppressed["emailAddresses"] == _keys("emailAddresses", OLD)


class TestProfileEntries:
    PROFILE = {"source": {"type": "PROFILE", "id": "p1"}}

    def test_a_profile_entry_local_holds_is_neither_kept_nor_pending(self) -> None:
        """Inbound imports a profile's email too; Google still holds it."""
        merged = merge_for_push(
            {"emailAddresses": [ADA]},
            {"emailAddresses": [{"metadata": self.PROFILE, **ADA}]},
            synced_base={"emailAddresses": _keys("emailAddresses", ADA)},
        )

        assert merged.payload["emailAddresses"] == [ADA]
        assert merged.pending_import is False


class TestUnimportable:
    def test_a_pushed_entry_inbound_cannot_import_is_not_doubled(self) -> None:
        """Google echoes it back with no key, so it must not be kept beside it.

        The echo carries what Google adds (a formatted value, the country
        name) and the pushed copy its primary flag; the parts the push writes
        are what make it the same entry.
        """
        pushed = {
            "streetAddress": "10 Downing St",
            "region": "London",
            "countryCode": "AU",
            "metadata": {"primary": True},
        }
        echoed = {
            "metadata": {"primary": True, **CONTACT_SOURCE},
            "streetAddress": "10 Downing St",
            "region": "London",
            "countryCode": "AU",
            "country": "Australia",
            "formattedValue": "10 Downing St\nLondon\nAustralia",
        }

        merged = merge_for_push(
            {"addresses": [pushed]},
            {"addresses": [echoed]},
            synced_base={"addresses": frozenset()},
        )

        assert merged.payload["addresses"] == [pushed]


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


class TestProfileBirthday:
    def test_a_birthday_added_to_the_linked_profile_is_owed_to_the_pull(
        self,
    ) -> None:
        """Inbound imports a profile's birthday too; the contact has none."""
        merged = merge_for_push(
            {"birthdays": []},
            {
                "birthdays": [
                    {
                        "metadata": {"source": {"type": "PROFILE"}},
                        "date": {"year": 1815, "month": 12, "day": 10},
                    }
                ]
            },
            synced_base={"birthdays": frozenset()},
        )

        assert merged.payload["birthdays"] == []
        assert merged.pending_import is True
        # Not the contact's yet: the next base must not count it as synced.
        assert merged.kept["birthdays"] == _keys(
            "birthdays", {"date": {"year": 1815, "month": 12, "day": 10}}
        )


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

    def test_a_birthday_deleted_in_google_is_not_pushed_back(self) -> None:
        merged = _merge("birthdays", [self.BORN], google=[], base=[self.BORN])

        assert "birthdays" not in merged.payload
        assert merged.pending_import is True

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


ACME = {"current": True, "name": "Acme", "title": "Engineer"}
GLOBEX = {"name": "Globex", "title": "Director"}
PROFILE_SOURCE = {"source": {"type": "PROFILE", "id": "p1"}}


class TestOrganizations:
    """The organization inbound imports is the contact's company (#1938).

    Local holding no company sends ``organizations: []``; the base tells a
    company cleared locally from one Google added since the last sync.
    """

    def test_a_company_cleared_locally_is_cleared(self) -> None:
        merged = _merge("organizations", [], google=[ACME], base=[ACME])

        assert merged.payload["organizations"] == []
        assert merged.pending_import is False
        assert "organizations" in merged.merged_fields

    def test_a_cleared_company_keeps_googles_other_organizations(self) -> None:
        """The next one inbound reads is owed to the pull, and kept out of the base."""
        merged = _merge("organizations", [], google=[ACME, GLOBEX], base=[ACME])

        assert merged.payload["organizations"] == [GLOBEX]
        assert merged.kept["organizations"] == _keys("organizations", GLOBEX)
        assert merged.pending_import is True

    def test_a_second_push_before_the_pull_keeps_the_organization_left(
        self,
    ) -> None:
        """The first push's base holds Globex less what it kept: nothing."""
        merged = _merge("organizations", [], google=[GLOBEX], base=[])

        assert "organizations" not in merged.payload
        assert merged.pending_import is True

    def test_a_company_added_in_google_is_kept_and_owed_to_the_pull(self) -> None:
        merged = _merge("organizations", [], google=[ACME], base=[])

        assert "organizations" not in merged.payload
        assert merged.pending_import is True

    def test_a_company_edited_in_google_wins_over_the_unchanged_local_one(
        self,
    ) -> None:
        edited = {**ACME, "title": "Chief Engineer"}

        merged = _merge("organizations", [ACME], google=[edited], base=[ACME])

        assert "organizations" not in merged.payload
        assert merged.pending_import is True

    def test_a_company_deleted_in_google_is_not_pushed_back(self) -> None:
        merged = _merge("organizations", [ACME], google=[], base=[ACME])

        assert "organizations" not in merged.payload
        assert merged.pending_import is True

    def test_a_company_edited_locally_is_written_over_googles(self) -> None:
        renamed = {"current": True, "name": "Acme Ltd", "title": "Engineer"}
        held = {**ACME, "department": "R&D"}

        merged = _merge("organizations", [renamed], google=[held], base=[ACME])

        assert merged.payload["organizations"] == [{**renamed, "department": "R&D"}]
        assert merged.pending_import is False

    def test_no_company_on_either_side_leaves_the_field_alone(self) -> None:
        merged = _merge("organizations", [], google=[], base=[])

        assert "organizations" not in merged.payload
        assert merged.pending_import is False

    def test_a_company_from_the_linked_profile_cannot_be_cleared(self) -> None:
        """The pull imports it again, so it is owed rather than silently kept."""
        merged = merge_for_push(
            {"organizations": []},
            {"organizations": [{"metadata": PROFILE_SOURCE, **ACME}]},
            synced_base={"organizations": _keys("organizations", ACME)},
        )

        assert "organizations" not in merged.payload
        assert merged.pending_import is True


NOTE = {"value": "Met at the conference", "contentType": "TEXT_PLAIN"}
OTHER_NOTE = {"value": "Likes tea", "contentType": "TEXT_PLAIN"}


class TestBiographies:
    """Inbound imports every biography as a note (#1938, #1822)."""

    def test_notes_cleared_locally_are_cleared(self) -> None:
        merged = _merge(
            "biographies", [], google=[NOTE, OTHER_NOTE], base=[NOTE, OTHER_NOTE]
        )

        assert merged.payload["biographies"] == []
        assert merged.pending_import is False

    def test_a_note_added_in_google_is_kept_and_owed_to_the_pull(self) -> None:
        merged = _merge("biographies", [], google=[NOTE, OTHER_NOTE], base=[NOTE])

        assert "biographies" not in merged.payload
        assert merged.pending_import is True

    def test_a_note_edited_in_google_wins_over_the_unchanged_local_one(
        self,
    ) -> None:
        edited = {**NOTE, "value": "Met at the conference in Leeds"}

        merged = _merge("biographies", [NOTE], google=[edited], base=[NOTE])

        assert "biographies" not in merged.payload
        assert merged.pending_import is True

    def test_a_note_edited_locally_is_written_over_googles(self) -> None:
        merged = _merge("biographies", [OTHER_NOTE], google=[NOTE], base=[NOTE])

        assert merged.payload["biographies"] == [OTHER_NOTE]
        assert merged.pending_import is False

    def test_no_notes_on_either_side_leaves_the_field_alone(self) -> None:
        merged = _merge("biographies", [], google=[], base=[])

        assert "biographies" not in merged.payload
        assert merged.pending_import is False

    def test_a_note_from_the_linked_profile_cannot_be_cleared(self) -> None:
        merged = merge_for_push(
            {"biographies": []},
            {"biographies": [NOTE, {"metadata": PROFILE_SOURCE, **OTHER_NOTE}]},
            synced_base={"biographies": _keys("biographies", NOTE, OTHER_NOTE)},
        )

        assert merged.payload["biographies"] == []
        assert merged.pending_import is True


class TestResolveSyncedBase:
    CURRENT = {
        "etag": "e2",
        "emailAddresses": _google(ADA),
        "organizations": _google(ACME),
    }

    def test_a_recorded_base_is_used_as_recorded(self) -> None:
        recorded = {field: frozenset({"k"}) for field in BASE_FIELDS}

        assert (
            resolve_synced_base(recorded, self.CURRENT, synced_version="e2") is recorded
        )

    def test_a_field_the_record_predates_is_read_from_an_unchanged_person(
        self,
    ) -> None:
        """A base recorded before organizations joined it (#1938)."""
        recorded = {"emailAddresses": frozenset({"k"})}

        base = resolve_synced_base(recorded, self.CURRENT, synced_version="e2")

        assert base["emailAddresses"] == frozenset({"k"})
        assert base["organizations"] == _keys("organizations", ACME)

    def test_a_field_the_record_predates_is_empty_for_a_changed_person(
        self,
    ) -> None:
        """Recorded empty, so the push that keeps Google's company keeps that base."""
        recorded = {"emailAddresses": frozenset({"k"})}

        base = resolve_synced_base(recorded, self.CURRENT, synced_version="e1")

        assert base["organizations"] == frozenset()

    def test_a_company_google_added_before_the_deploy_survives_two_pushes(
        self,
    ) -> None:
        """The second push's etag is the first's own: it must not reread the base."""
        recorded = {"emailAddresses": _keys("emailAddresses", ADA)}
        first_base = resolve_synced_base(recorded, self.CURRENT, synced_version="e1")
        first = merge_for_push(
            {"emailAddresses": [ADA], "organizations": []},
            self.CURRENT,
            synced_base=first_base,
        )
        # The update leaves organizations out, so it keeps the resolved base.
        second_base = resolve_synced_base(first_base, self.CURRENT, synced_version="e2")
        second = merge_for_push(
            {"emailAddresses": [ADA], "organizations": []},
            self.CURRENT,
            synced_base=second_base,
        )

        assert "organizations" not in first.payload
        assert "organizations" not in second.payload
        assert second.pending_import is True

    def test_without_a_record_an_unchanged_person_is_its_own_base(self) -> None:
        base = resolve_synced_base(None, self.CURRENT, synced_version="e2")

        assert base["emailAddresses"] == _keys("emailAddresses", ADA)

    def test_without_a_record_a_changed_person_has_an_empty_base(self) -> None:
        """Nothing tells an addition from a deletion, so keep everything.

        Each field is recorded empty, so a push that leaves one out keeps it so.
        """
        assert resolve_synced_base(None, self.CURRENT, synced_version="e1") == {
            field: frozenset() for field in BASE_FIELDS
        }


class TestFieldsThePushLeavesOut:
    """A field the payload omits keeps Google's value, unmerged (#1938).

    Every owned field is sent once it is loaded, so a field is left out only
    when the push did not load it: local's value is unknown. Google's stands,
    nothing merged it, and the backend skips the pulls older than the push, so
    the next pull must import it.
    """

    def test_a_value_google_holds_in_an_omitted_field_is_pending_import(
        self,
    ) -> None:
        merged = merge_for_push(
            {"emailAddresses": [ADA]},
            {
                "emailAddresses": _google(ADA),
                "organizations": _google({"name": "Analytical Engines"}),
            },
            synced_base={"emailAddresses": _keys("emailAddresses", ADA)},
        )

        assert "organizations" not in merged.payload
        assert merged.pending_import is True

    @pytest.mark.parametrize("held", [None, []])
    def test_an_omitted_field_google_holds_nothing_in_is_not(
        self, held: list[dict[str, Any]] | None
    ) -> None:
        merged = merge_for_push(
            {"emailAddresses": [ADA]},
            {"emailAddresses": _google(ADA), "organizations": held},
            synced_base={"emailAddresses": _keys("emailAddresses", ADA)},
        )

        assert merged.pending_import is False

    def test_a_field_google_reads_but_the_merge_does_not_own_is_ignored(
        self,
    ) -> None:
        """``metadata`` and the like are never imported as contact data."""
        merged = merge_for_push(
            {"emailAddresses": [ADA]},
            {"emailAddresses": _google(ADA), "metadata": {"sources": []}},
            synced_base={"emailAddresses": _keys("emailAddresses", ADA)},
        )

        assert merged.pending_import is False
