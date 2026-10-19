"""A push owns exactly the Google entries inbound sync imports (#1788).

Google replaces every field a push names wholesale, so each pushed field has a
merge policy in ``person_merge.FIELD_POLICIES`` that keeps what inbound could
not import. These tests stop the next field from being added without one:

* every field the push can send has a policy, and every policy a field;
* a person full of entries inbound skips, imported and pushed back unchanged,
  keeps every one of them in Google.
"""

from collections.abc import Callable
from typing import Any

import pytest
from core_shared.models.contacts.entities import Contact

from api_models import GooglePerson
from person_merge import FIELD_POLICIES, merge_with_current_person
from transformer import GoogleContactTransformer
from worker import _transform_contact_to_google_person

_CONTACT_SOURCE = {"source": {"type": "CONTACT", "id": "c1"}}


def _entry(**fields: Any) -> dict[str, Any]:
    """A contact-source entry as Google returns it."""
    return {"metadata": _CONTACT_SOURCE, **fields}


# Entries inbound sync cannot import, each a way a push used to wipe Google.
_UNIMPORTED: dict[str, list[dict[str, Any]]] = {
    "nicknames": [_entry(value="AL", type="INITIALS")],
    "emailAddresses": [_entry(value="not an email", type="work")],
    "phoneNumbers": [_entry(value="ask reception")],
    "addresses": [_entry(streetAddress="2 Nowhere Rd", city="Sydney", type="home")],
    "birthdays": [_entry(text="sometime in spring")],
    "events": [_entry(type="Graduation", date={"year": 2010, "month": 3, "day": 4})],
    "organizations": [_entry(name="Old Co", current=False)],
}

# What inbound does import, so the push has something of its own to send.
_IMPORTED: dict[str, list[dict[str, Any]]] = {
    "names": [
        {
            "metadata": {"primary": True, **_CONTACT_SOURCE},
            "givenName": "Ada",
            "familyName": "Lovelace",
            "honorificPrefix": "Dr",
        }
    ],
    "nicknames": [{"metadata": {"primary": True, **_CONTACT_SOURCE}, "value": "Ada"}],
    "emailAddresses": [_entry(value="ada@example.com")],
    "phoneNumbers": [_entry(value="0400 000 000", canonicalForm="+61400000000")],
    "addresses": [_entry(streetAddress="1 Main St", countryCode="AU")],
    "events": [_entry(type="anniversary", date={"year": 1835, "month": 7, "day": 8})],
    "organizations": [_entry(name="Engines", title="Analyst", current=True)],
    "biographies": [_entry(value="Met at the Analytical Society")],
    "memberships": [
        {
            "contactGroupMembership": {
                "contactGroupResourceName": "contactGroups/myContacts"
            }
        }
    ],
}


def _current_person() -> dict[str, Any]:
    """The person Google holds: everything inbound imports, then what it skips."""
    fields = _IMPORTED.keys() | _UNIMPORTED.keys()
    return {
        "resourceName": "people/c1",
        "etag": "etag",
        **{
            field: [*_IMPORTED.get(field, []), *_UNIMPORTED.get(field, [])]
            for field in fields
        },
    }


def _push_contact(contact: Contact, *, with_organization: bool) -> dict[str, Any]:
    """The contact dict a push builds its payload from, as the loaders shape it.

    The cron push loads no company or job title; the event push does.
    """
    loaded: dict[str, Any] = {
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "middle_name": contact.middle_name,
        "nick_name": contact.nick_name,
        "is_favourite": contact.is_favourite,
        "methods": [
            {
                "method_type": method.method_type.value,
                "value": method.value,
                "label": method.label,
                "is_primary": method.is_primary,
                "is_archived": method.is_archived,
            }
            for method in contact.methods or []
        ],
        "addresses": [
            {
                "label": address.label,
                "street_line_1": address.street_line_1,
                "street_line_2": address.street_line_2,
                "locality": address.locality,
                "region": address.region,
                "postal_code": address.postal_code,
                "country_code": address.country_code,
                "is_primary": address.is_primary,
                "is_archived": address.is_archived,
            }
            for address in contact.addresses or []
        ],
        "notes": [{"content": note.content} for note in contact.notes or []],
        "tags": [str(tag.name) for tag in contact.tags or []],
        "important_dates": [
            {
                "date_type": date.date_type.value,
                "precision": date.precision.value,
                "year": date.year,
                "month": date.month,
                "day": date.day,
            }
            for date in contact.important_dates or []
        ],
        "group_name_to_resource": {},
    }
    if with_organization:
        loaded["company"] = contact.company
        loaded["job_title"] = contact.job_title
    return loaded


def _writable(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry as a push may send it: without Google's output-only parts."""
    return {k: v for k, v in entry.items() if k not in {"metadata", "formattedType"}}


def test_every_pushed_field_has_a_merge_policy() -> None:
    """A field the push sends without a policy wipes whatever inbound skipped."""
    contact = {
        "first_name": "Ada",
        "nick_name": "Ada",
        "company": "Engines",
        "job_title": "Analyst",
        "methods": [{"method_type": "email", "value": "ada@example.com"}],
        "addresses": [{"street_line_1": "1 Main St", "country_code": "AU"}],
        "notes": [{"content": "Met at the Analytical Society"}],
        "tags": [],
        "group_name_to_resource": {},
        "important_dates": [],
    }

    payload = _transform_contact_to_google_person(contact)

    assert payload.keys() == FIELD_POLICIES.keys()


@pytest.mark.parametrize("with_organization", [False, True], ids=["cron", "event"])
@pytest.mark.parametrize(
    ("field", "entry"),
    [
        pytest.param(field, entry, id=field)
        for field, entries in _UNIMPORTED.items()
        for entry in entries
    ],
)
def test_an_unchanged_round_trip_keeps_what_inbound_skipped(
    field: str, entry: dict[str, Any], with_organization: bool
) -> None:
    current = _current_person()
    contact = GoogleContactTransformer(user_id="1").transform_person(
        GooglePerson.model_validate(current)
    )
    payload = _transform_contact_to_google_person(
        _push_contact(contact, with_organization=with_organization)
    )

    merged = merge_with_current_person(payload, current)

    assert field not in merged or _writable(entry) in merged[field]


def _pull(person: dict[str, Any]) -> Contact:
    """The contact inbound sync builds from a person."""
    return GoogleContactTransformer(user_id="1").transform_person(
        GooglePerson.model_validate(person)
    )


def _set_nickname(value: str | None) -> Callable[[Contact], None]:
    def edit(contact: Contact) -> None:
        contact.nick_name = value

    return edit


def _clear_addresses(contact: Contact) -> None:
    contact.addresses = []


def _clear_methods(contact: Contact) -> None:
    contact.methods = []


def _unchanged(contact: Contact) -> None:
    return None


@pytest.mark.parametrize("with_organization", [False, True], ids=["cron", "event"])
@pytest.mark.parametrize(
    "edit",
    [
        _unchanged,
        _set_nickname("Countess"),
        _set_nickname(None),
        _clear_addresses,
        _clear_methods,
    ],
    ids=["unchanged", "nickname-renamed", "nickname-cleared", "addresses", "methods"],
)
def test_a_pull_after_the_push_reads_back_what_was_pushed(
    edit: Callable[[Contact], None], with_organization: bool
) -> None:
    """Keeping an entry must not make it the value the next pull imports.

    A kept entry inbound would read as the contact's own (a surviving nickname
    after the local one is cleared) undoes the local edit on the next pull.
    Pushing the same contact again must leave Google as the first push did.
    """
    current = _current_person()
    contact = _pull(current)
    edit(contact)
    pushed = _push_contact(contact, with_organization=with_organization)
    payload = _transform_contact_to_google_person(pushed)

    after_push = {**current, **merge_with_current_person(payload, current)}
    after_second_push = {
        **after_push,
        **merge_with_current_person(payload, after_push),
    }

    assert _push_contact(_pull(after_push), with_organization=with_organization) == (
        pushed
    )
    assert after_second_push == after_push
