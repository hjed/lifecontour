"""Keys of the Google entries a sync agreed on, per field (#1861).

The pull records these keys for the person it read, and the push for the
person Google returns. The next push merges against them: an entry Google holds
whose keys the base lacks was added in Google since, so it is kept rather than
deleted. See ``core_shared.sync_base``.

A key covers only the value inbound imports - an email's address, a phone's
number, an address's parts, a birthday's date - never its label, primary flag
or formatting, so the pull, the push and Google's response agree on an entry
however each presents it. A phone carries a key per spelling - E.164, and the
digits as typed - since the push sends a number as typed and Google answers
with it canonical: two entries are one when any of their keys match
(``three_way_entries``). An entry inbound does not import has no keys: it was
never held locally.
"""

from collections.abc import Callable, Mapping
from typing import Any, Final, Literal

import phonenumbers
from core_shared.sync_base import SyncedEntries, entry_key
from pydantic import BaseModel, ValidationError

from api_models import (
    GoogleAddress,
    GoogleBirthday,
    GoogleEmailAddress,
    GooglePerson,
    GooglePhoneNumber,
)
from transformer import (
    import_address,
    import_birthday,
    import_email,
    import_phone,
)

type Keys = frozenset[str]

_NO_KEYS: Final[Keys] = frozenset()

type BaseField = Literal["emailAddresses", "phoneNumbers", "addresses", "birthdays"]

# The Google fields the push merges against a base, in the person's raw names.
BASE_FIELDS: Final[tuple[BaseField, ...]] = (
    "emailAddresses",
    "phoneNumbers",
    "addresses",
    "birthdays",
)


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
    """The phone's keys: its E.164 form, and its digits as typed.

    Google answers a number pushed as typed ("0412 345 678") with an E.164
    ``canonicalForm`` ("+61412345678") beside the typed ``value``, so the
    typed digits match the local copy and the E.164 form matches a copy
    typed differently. A national number alone names no country, so it is
    never read as one: the same digits in two countries are two phones.
    """
    if import_phone(phone) is None:
        return _NO_KEYS
    keys = set()
    if (e164 := _e164(phone.canonical_form) or _e164(phone.value)) is not None:
        keys.add(entry_key("phone", "e164", e164))
    if digits := "".join(char for char in phone.value if char.isdigit()):
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
    }
    return readers[field](entry)


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
    }
    return {field: _NO_KEYS.union(*keys) for field, keys in keyed.items()}


def raw_synced_entries(
    person: Mapping[str, Any], fallback_country: str | None
) -> SyncedEntries:
    """:func:`synced_entries_of` for a raw People API person, as the push holds it."""
    return {
        field: _NO_KEYS.union(
            *(
                raw_entry_keys(field, entry, fallback_country)
                for entry in person.get(field) or []
            )
        )
        for field in BASE_FIELDS
    }
