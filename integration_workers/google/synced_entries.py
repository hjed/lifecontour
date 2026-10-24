"""Keys of the Google entries a sync agreed on, per field (#1861).

The pull records these keys for the person it read, and the push for the
person Google returns. The next push merges against them: an entry Google holds
whose key the base lacks was added in Google since, so it is kept rather than
deleted. See ``core_shared.sync_base``.

A key covers only the value inbound imports - an email's address, a phone's
canonical form, an address's parts, a birthday's date - never its label,
primary flag or formatting, so the pull, the push and Google's response agree
on an entry however each presents it. An entry inbound does not import has no
key: it was never held locally.
"""

from collections.abc import Callable, Mapping
from typing import Any, Final, Literal

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


def email_key(email: GoogleEmailAddress) -> str | None:
    """The email's key, or None when inbound does not import it."""
    method = import_email(email)
    return None if method is None else entry_key("email", _normalised(method.value))


def phone_key(phone: GooglePhoneNumber) -> str | None:
    """The phone's key, from the canonical form inbound reads when Google has one."""
    method = import_phone(phone)
    return None if method is None else entry_key("phone", "".join(method.value.split()))


def address_key(address: GoogleAddress, fallback_country: str | None) -> str | None:
    """The address's key, read with the country a countryless one is given.

    The street lines count as one: the push folds the second line into
    ``streetAddress``, so an address pulled with an ``extendedAddress`` must
    key as the folded one Google then holds.
    """
    imported = import_address(address, fallback_country)
    if imported is None:
        return None
    street = " ".join(
        line for line in (imported.street_line_1, imported.street_line_2) if line
    )
    # Normalised as ``transformer._address_key`` does, from the parts rather than a
    # rebuilt address: one line holding both could fail its length check.
    parts = (
        street,
        imported.locality,
        imported.region,
        imported.postal_code,
        imported.country_code,
    )
    return entry_key(
        "address", *(" ".join((part or "").split()).casefold() for part in parts)
    )


def birthday_key(birthday: GoogleBirthday) -> str | None:
    """The birthday's key, or None for a text-only one inbound cannot read."""
    imported = import_birthday(birthday)
    if imported is None:
        return None
    return entry_key(
        "birthday",
        imported.precision.value,
        imported.year,
        imported.month,
        imported.day,
    )


def _raw[M: BaseModel](
    model: type[M], key: Callable[[M], str | None]
) -> Callable[[Mapping[str, Any]], str | None]:
    def read(entry: Mapping[str, Any]) -> str | None:
        try:
            return key(model.model_validate(entry))
        except ValidationError:
            return None

    return read


def raw_entry_key(
    field: BaseField, entry: Mapping[str, Any], fallback_country: str | None
) -> str | None:
    """The key of one raw People API entry, as the push holds it."""
    readers: dict[BaseField, Callable[[Mapping[str, Any]], str | None]] = {
        "emailAddresses": _raw(GoogleEmailAddress, email_key),
        "phoneNumbers": _raw(GooglePhoneNumber, phone_key),
        "addresses": _raw(
            GoogleAddress, lambda address: address_key(address, fallback_country)
        ),
        "birthdays": _raw(GoogleBirthday, birthday_key),
    }
    return readers[field](entry)


def synced_entries_of(
    person: GooglePerson, fallback_country: str | None
) -> dict[BaseField, frozenset[str]]:
    """The keys of every entry inbound imports from ``person``, per field.

    Every base field is present, empty or not: an empty field records that the
    sync agreed the contact held nothing there.
    """
    keyed: dict[BaseField, list[str | None]] = {
        "emailAddresses": [email_key(e) for e in person.email_addresses],
        "phoneNumbers": [phone_key(p) for p in person.phone_numbers],
        "addresses": [address_key(a, fallback_country) for a in person.addresses],
        "birthdays": [birthday_key(b) for b in person.birthdays],
    }
    return {
        field: frozenset(key for key in keys if key is not None)
        for field, keys in keyed.items()
    }


def raw_synced_entries(
    person: Mapping[str, Any], fallback_country: str | None
) -> SyncedEntries:
    """:func:`synced_entries_of` for a raw People API person, as the push holds it."""
    return {
        field: frozenset(
            key
            for entry in person.get(field) or []
            if (key := raw_entry_key(field, entry, fallback_country)) is not None
        )
        for field in BASE_FIELDS
    }
