"""Keys of the Google entries a sync agreed on, per field (#1861).

The pull records these keys for the person it read, and the push for the
person Google returns. The next push merges against them: an entry Google holds
whose keys the base lacks was added in Google since, so it is kept rather than
deleted. See ``core_shared.sync_base``.

A key covers only the value inbound imports - an email's address, a phone's
number, an address's parts, a birthday's or anniversary's date, a nickname's
text, each part of a name - never its label, primary flag
or formatting, so the pull, the push and Google's response agree on an entry
however each presents it. A phone carries a key per spelling - E.164, and the
digits as typed - since the push sends a number as typed and Google answers
with it canonical: two entries are one when any of their keys match
(``three_way_entries``). An entry inbound does not import has no keys: it was
never held locally.

A name and the imported organization are merged part by part, so they carry a
key per part (``name_part_keys``, ``organization_part_keys``), an empty part
included: the base then records that the name had no middle name.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final, Literal

import phonenumbers
from core_shared.models.contacts.sync_scope import ContactSyncField
from core_shared.sync_base import SyncedEntries, entry_key
from pydantic import BaseModel, ValidationError

from api_models import (
    GoogleAddress,
    GoogleBiography,
    GoogleBirthday,
    GoogleEmailAddress,
    GoogleNickname,
    GoogleOrganization,
    GooglePerson,
    GooglePersonEvent,
    GooglePhoneNumber,
)
from transformer import (
    import_address,
    import_birthday,
    import_email,
    import_event,
    import_phone,
    imported_organization_index,
    select_nickname,
)

type Keys = frozenset[str]

_NO_KEYS: Final[Keys] = frozenset()

type BaseField = Literal[
    "emailAddresses",
    "phoneNumbers",
    "addresses",
    "birthdays",
    "organizations",
    "biographies",
    "nicknames",
    "events",
    "names",
]

# The Google fields the push merges against a base, in the person's raw names.
BASE_FIELDS: Final[tuple[BaseField, ...]] = (
    "emailAddresses",
    "phoneNumbers",
    "addresses",
    "birthdays",
    "organizations",
    "biographies",
    "nicknames",
    "events",
    "names",
)

# The parts of a name and an organization the local contact owns, raw names.
NAME_PARTS: Final = ("givenName", "familyName", "middleName")
ORGANIZATION_PARTS: Final = ("name", "title")

# Inbound's given name for a person Google holds none for.
_UNKNOWN_GIVEN_NAME: Final = "Unknown"


def _normalised(value: str) -> str:
    return " ".join(value.split()).casefold()


def email_keys(email: GoogleEmailAddress) -> Keys:
    """The email's key, or none when inbound does not import it."""
    method = import_email(email)
    if method is None:
        return _NO_KEYS
    return frozenset({entry_key("email", _normalised(method.value))})


def _e164(number: str | None) -> str | None:
    """An international number in E.164, or None when it names no country."""
    if not number or not number.strip().startswith("+"):
        return None
    try:
        parsed = phonenumbers.parse(number, None)
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def phone_keys(phone: GooglePhoneNumber) -> Keys:
    """The phone's keys: its E.164 form, and the digits of a number typed without ``+``.

    Google answers a number pushed as typed ("0412 345 678") with an E.164
    ``canonicalForm`` ("+61412345678") beside the typed ``value``, so the
    typed digits match the local copy and the E.164 form matches a copy
    typed differently. A number typed with ``+`` is fully named by its E.164
    form, so it has no typed key: "+65 6500 1234" never matches a US
    "(656) 500-1234" by their shared digits.
    """
    if import_phone(phone) is None:
        return _NO_KEYS
    keys = set()
    if (e164 := _e164(phone.canonical_form) or _e164(phone.value)) is not None:
        keys.add(entry_key("phone", "e164", e164))
    typed = phone.value.strip()
    if not typed.startswith("+") and (
        digits := "".join(char for char in typed if char.isdigit())
    ):
        keys.add(entry_key("phone", "typed", digits))
    return frozenset(keys)


def address_keys(address: GoogleAddress, fallback_country: str | None) -> Keys:
    """The address's key, read with the country a countryless one is given.

    The street lines count as one: the push folds the second line into
    ``streetAddress``, so an address pulled with an ``extendedAddress`` must
    key as the folded one Google then holds.
    """
    imported = import_address(address, fallback_country)
    if imported is None:
        return _NO_KEYS
    street = " ".join(
        line for line in (imported.street_line_1, imported.street_line_2) if line
    )
    # Normalised as ``transformer._address_key`` does, from the parts rather
    # than a rebuilt address: one line holding both could fail its length check.
    parts = (
        street,
        imported.locality,
        imported.region,
        imported.postal_code,
        imported.country_code,
    )
    normalised = (" ".join((part or "").split()).casefold() for part in parts)
    return frozenset({entry_key("address", *normalised)})


def birthday_keys(birthday: GoogleBirthday) -> Keys:
    """The birthday's key, or none for a text-only one inbound cannot read."""
    imported = import_birthday(birthday)
    if imported is None:
        return _NO_KEYS
    return frozenset(
        {
            entry_key(
                "birthday",
                imported.precision.value,
                imported.year,
                imported.month,
                imported.day,
            )
        }
    )


def organization_keys(organization: GoogleOrganization) -> Keys:
    """The organization's key: its company and job title, stripped as inbound reads them.

    None when both are blank, which inbound reads as no company at all. Only the
    organization inbound imports is in a base (:func:`imported_organization_index`).
    """
    company = (organization.name or "").strip()
    title = (organization.title or "").strip()
    if not company and not title:
        return _NO_KEYS
    return frozenset({entry_key("organization", company, title)})


def biography_keys(biography: GoogleBiography) -> Keys:
    """The biography's key: its text, stripped but with its case, as a note holds it."""
    value = biography.value.strip()
    if not value:
        return _NO_KEYS
    return frozenset({entry_key("biography", value)})


def imported_part(entry: Mapping[str, Any], part: str) -> str:
    """One owned part of a raw name or organization, as inbound reads it."""
    value = str(entry.get(part) or "").strip()
    if part == "givenName" and not value:
        return _UNKNOWN_GIVEN_NAME
    return value


def name_part_keys(entry: Mapping[str, Any]) -> dict[str, str]:
    """The key of each part of a raw name, empty parts included."""
    return {
        part: entry_key("name", part, imported_part(entry, part)) for part in NAME_PARTS
    }


def organization_part_keys(entry: Mapping[str, Any]) -> Keys:
    """The keys of a raw organization's company and job title, apart.

    None for one inbound reads as no company at all. They sit beside the
    combined key (:func:`organization_keys`) in the base, which the whole-entry
    decisions read; a base from before them holds only that one.
    """
    if not any(imported_part(entry, part) for part in ORGANIZATION_PARTS):
        return _NO_KEYS
    return frozenset(organization_part_key(entry, part) for part in ORGANIZATION_PARTS)


def organization_part_key(entry: Mapping[str, Any], part: str) -> str:
    """The key of one part of a raw organization."""
    return entry_key("organization-part", part, imported_part(entry, part))


def nickname_keys(nickname: GoogleNickname) -> Keys:
    """The nickname's key: its text, stripped as inbound reads it.

    Only the nickname inbound imports is in a base (:func:`chosen_nickname_index`).
    """
    value = (nickname.value or "").strip()
    if not value:
        return _NO_KEYS
    return frozenset({entry_key("nickname", value)})


def event_keys(event: GooglePersonEvent) -> Keys:
    """The event's key: its type and date, or none for an event inbound skips."""
    imported = import_event(event)
    if imported is None:
        return _NO_KEYS
    return frozenset(
        {
            entry_key(
                imported.date_type.value,
                imported.precision.value,
                imported.year,
                imported.month,
                imported.day,
            )
        }
    )


def chosen_nickname_index(current: Sequence[Mapping[str, Any]]) -> int | None:
    """The index of the raw nickname inbound reads into the contact."""
    parsed: list[tuple[int, GoogleNickname]] = []
    for index, entry in enumerate(current):
        try:
            parsed.append((index, GoogleNickname.model_validate(entry)))
        except ValidationError:
            continue
    chosen = select_nickname([nickname for _, nickname in parsed])
    return next((index for index, n in parsed if n is chosen), None)


def _raw[M: BaseModel](
    model: type[M], keys: Callable[[M], Keys]
) -> Callable[[Mapping[str, Any]], Keys]:
    def read(entry: Mapping[str, Any]) -> Keys:
        try:
            return keys(model.model_validate(entry))
        except ValidationError:
            return _NO_KEYS

    return read


def raw_entry_keys(
    field: BaseField, entry: Mapping[str, Any], fallback_country: str | None
) -> Keys:
    """The keys of one raw People API entry, as the push holds it."""
    readers: dict[BaseField, Callable[[Mapping[str, Any]], Keys]] = {
        "emailAddresses": _raw(GoogleEmailAddress, email_keys),
        "phoneNumbers": _raw(GooglePhoneNumber, phone_keys),
        "addresses": _raw(
            GoogleAddress, lambda address: address_keys(address, fallback_country)
        ),
        "birthdays": _raw(GoogleBirthday, birthday_keys),
        "organizations": _raw(GoogleOrganization, organization_keys),
        "biographies": _raw(GoogleBiography, biography_keys),
        "nicknames": _raw(GoogleNickname, nickname_keys),
        "events": _raw(GooglePersonEvent, event_keys),
        "names": lambda name: frozenset(name_part_keys(name).values()),
    }
    return readers[field](entry)


def imported_name_index(current: Sequence[Mapping[str, Any]]) -> int | None:
    """The index of the raw name inbound reads: the primary one, else the first."""
    if not current:
        return None
    return next(
        (
            index
            for index, name in enumerate(current)
            if (name.get("metadata") or {}).get("primary")
        ),
        0,
    )


def imported_name(current: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The raw name inbound reads; empty for a person with none.

    Inbound reads no name as the given name "Unknown", so even no name has
    keys (:func:`name_part_keys`): a name Google adds later is then an edit
    of the placeholder, not a conflict with it.
    """
    index = imported_name_index(current)
    return {} if index is None else current[index]


def _raw_imported(
    field: BaseField, entries: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """The raw entries of ``field`` inbound imports.

    One organization, nickname and name, and every entry of the other fields.
    """
    if field == "organizations":
        index = imported_organization_index([e.get("current") for e in entries])
    elif field == "nicknames":
        index = chosen_nickname_index(entries)
    elif field == "names":
        return [imported_name(entries)]
    else:
        return list(entries)
    return [] if index is None else [entries[index]]


def _imported_organization(
    organizations: Sequence[GoogleOrganization],
) -> list[GoogleOrganization]:
    """The organization inbound imports, if any, as a list."""
    index = imported_organization_index([o.current for o in organizations])
    return [] if index is None else [organizations[index]]


def _dumped(entry: BaseModel) -> dict[str, Any]:
    """A parsed entry in the People API's own raw names."""
    return entry.model_dump(by_alias=True, exclude_none=True)


def synced_entries_of(
    person: GooglePerson, fallback_country: str | None
) -> dict[BaseField, Keys]:
    """The keys of every entry inbound imports from ``person``, per field.

    Every base field is present, empty or not: an empty field records that the
    sync agreed the contact held nothing there.
    """
    keyed: dict[BaseField, list[Keys]] = {
        "emailAddresses": [email_keys(e) for e in person.email_addresses],
        "phoneNumbers": [phone_keys(p) for p in person.phone_numbers],
        "addresses": [address_keys(a, fallback_country) for a in person.addresses],
        "birthdays": [birthday_keys(b) for b in person.birthdays],
        "organizations": [
            organization_keys(o) | organization_part_keys(_dumped(o))
            for o in _imported_organization(person.organizations)
        ],
        "biographies": [biography_keys(b) for b in person.biographies],
        "nicknames": [
            nickname_keys(n)
            for n in [select_nickname(person.nicknames)]
            if n is not None
        ],
        "events": [event_keys(e) for e in person.events],
        "names": [
            frozenset(
                name_part_keys(
                    imported_name([_dumped(name) for name in person.names])
                ).values()
            )
        ],
    }
    return {field: _NO_KEYS.union(*keys) for field, keys in keyed.items()}


def raw_synced_entries(
    person: Mapping[str, Any], fallback_country: str | None
) -> SyncedEntries:
    """:func:`synced_entries_of` for a raw People API person, as the push holds it."""
    synced: dict[str, Keys] = {}
    for field in BASE_FIELDS:
        entries: list[Mapping[str, Any]] = person.get(field) or []
        imported = _raw_imported(field, entries)
        synced[field] = _NO_KEYS.union(
            *(raw_entry_keys(field, entry, fallback_country) for entry in imported)
        )
        if field == "organizations":
            synced[field] |= _NO_KEYS.union(*map(organization_part_keys, imported))
    return synced


# The contact lists inbound sends as None when Google holds no entries in them,
# each with the base field that records what Google held.
LIST_BASES: Final[Mapping[ContactSyncField, BaseField]] = {
    ContactSyncField.ADDRESSES: "addresses",
    ContactSyncField.NOTES: "biographies",
}


def empty_at_source(person: GooglePerson) -> dict[ContactSyncField, BaseField]:
    """The lists ``person`` holds no entries in at all, with their base fields.

    The backend clears such a list when the link's base recorded entries for it:
    Google deleted them all since the last sync (#1909). An entry inbound cannot
    import still counts as held, since Google keeps it.
    """
    held: dict[ContactSyncField, list[Any]] = {
        ContactSyncField.ADDRESSES: person.addresses,
        ContactSyncField.NOTES: person.biographies,
    }
    return {field: base for field, base in LIST_BASES.items() if not held[field]}


def person_source_versions(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Each source's version time, from a person's ``metadata`` (#1938).

    Keyed ``"<type>/<id>"``, valued with Google's RFC 3339 ``updateTime``. A
    source without one leaves the person unordered, so it records none: a
    version missing from the record must never let an event look older.
    """
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        return {}
    versions: dict[str, str] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            return {}
        kind, source_id, at = (
            source.get("type"),
            source.get("id"),
            source.get("updateTime"),
        )
        if not (kind and source_id and isinstance(at, str) and at):
            return {}
        versions[f"{kind}/{source_id}"] = at
    return versions
