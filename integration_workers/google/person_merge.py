"""Merge a contact push into the Google person as it stands.

A push names fields in ``updatePersonFields`` and Google replaces each named
field wholesale, while the payload is built from the local contact alone. The
merge folds back the values of those fields the local model does not own, so a
push changes only what the local contact can represent (#1732).

The local contact owns exactly what inbound sync (``transformer.py``) imports,
and the merge asks the import itself: an entry its per-entry functions reject
(an address with no country code, an invalid email, a text-only birthday) is
one local never held, so the push keeps it (#1788). Every field a push can send
has a policy in ``FIELD_POLICIES``; ``tests/unit/test_push_field_ownership.py``
fails when one is added without. Values held by a person's profile rather than
the contact itself are never copied into the contact.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Literal, Protocol

import structlog
from pydantic import BaseModel, ValidationError

from api_models import (
    GoogleAddress,
    GoogleBirthday,
    GoogleEmailAddress,
    GoogleNickname,
    GooglePhoneNumber,
)
from transformer import (
    import_address,
    import_birthday,
    import_email,
    import_phone,
    select_nickname,
)

logger = structlog.get_logger()

type Entry = dict[str, Any]

# Name parts the local model cannot represent, kept from Google's name; the
# local contact owns given, family and middle name. unstructuredName is left out: Google formats the display name from the
# structured parts, and a stale free-form name could contradict a local rename.
_PRESERVED_NAME_KEYS = frozenset(
    {
        "honorificPrefix",
        "honorificSuffix",
        "phoneticFullName",
        "phoneticGivenName",
        "phoneticMiddleName",
        "phoneticFamilyName",
        "phoneticHonorificPrefix",
        "phoneticHonorificSuffix",
    }
)

# Organization parts the local contact owns (company and job title).
_OWNED_ORGANIZATION_KEYS = frozenset({"name", "title"})

# Event types the local contact owns, matching inbound sync's event type map.
_OWNED_EVENT_TYPES = frozenset({"anniversary"})

# Output-only parts of a field entry, never sent back to Google.
_OUTPUT_ONLY_KEYS = frozenset({"metadata", "formattedType"})

# Sources whose values belong to a profile, not to the contact being pushed.
_PROFILE_SOURCE_TYPES = frozenset({"PROFILE", "DOMAIN_PROFILE"})


class Omit(Enum):
    """A merge result that takes the field out of the update mask."""

    FIELD = "omit"


type Merged = list[Entry] | Literal[Omit.FIELD]


class FieldPolicy(Protocol):
    """How one pushed field merges into the field as Google holds it."""

    def merge(self, pushed: list[Entry], current: list[Entry]) -> Merged:
        """The value to send, or ``Omit.FIELD`` to leave Google's untouched."""
        ...


@dataclass(frozen=True)
class KeepUnimported:
    """Local owns the entries inbound imports; every other one is kept."""

    imports: Callable[[Entry], bool]

    def merge(self, pushed: list[Entry], current: list[Entry]) -> Merged:
        kept = [
            _writable(entry)
            for entry in current
            if _is_contact_entry(entry) and not self.imports(entry)
        ]
        return [*pushed, *kept]


@dataclass(frozen=True)
class KeepUnchosen:
    """Inbound reads one entry, which local owns; the others are kept beside it.

    The pushed entry leads the list, so it is the one inbound and the next push
    choose. With nothing pushed every entry goes: inbound would read a survivor
    as the contact's own, undoing the local clear on the next pull.
    """

    choose: Callable[[list[Entry]], int | None]

    def merge(self, pushed: list[Entry], current: list[Entry]) -> Merged:
        if not pushed:
            return pushed
        owned = self.choose(current)
        kept = [
            _writable(entry)
            for index, entry in enumerate(current)
            if index != owned and _is_contact_entry(entry)
        ]
        return [*pushed, *kept]


@dataclass(frozen=True)
class SingletonLeaveUnimported:
    """A field Google holds once per contact; one inbound cannot read stays.

    Google cannot hold a kept entry beside a pushed one, so a pushed value
    wins. With nothing pushed, a field whose entry inbound never imported
    leaves the update mask instead, so Google keeps it as it is.
    """

    imports: Callable[[Entry], bool]

    def merge(self, pushed: list[Entry], current: list[Entry]) -> Merged:
        contact_entries = [entry for entry in current if _is_contact_entry(entry)]
        if (
            not pushed
            and contact_entries
            and not any(self.imports(entry) for entry in contact_entries)
        ):
            return Omit.FIELD
        return pushed


@dataclass(frozen=True)
class MergedBy:
    """A field whose owned entry keeps parts of Google's (names, organizations)."""

    merge_entries: Callable[[list[Entry], list[Entry]], list[Entry]]

    def merge(self, pushed: list[Entry], current: list[Entry]) -> Merged:
        return self.merge_entries(pushed, current)


@dataclass(frozen=True)
class WhollyOwned:
    """Local holds every entry inbound imports, and inbound imports them all."""

    reason: str

    def merge(self, pushed: list[Entry], current: list[Entry]) -> Merged:
        return pushed


def _imported_by[M: BaseModel](
    model: type[M], import_entry: Callable[[M], object | None]
) -> Callable[[Entry], bool]:
    """Whether inbound imports a raw entry, read as inbound reads it.

    An entry inbound cannot even parse is one it never imported.
    """

    def imports(entry: Entry) -> bool:
        try:
            parsed = model.model_validate(entry)
        except ValidationError:
            return False
        return import_entry(parsed) is not None

    return imports


def _chosen_nickname(current: list[Entry]) -> int | None:
    """The index of the nickname inbound reads into the contact."""
    parsed: list[tuple[int, GoogleNickname]] = []
    for index, entry in enumerate(current):
        try:
            parsed.append((index, GoogleNickname.model_validate(entry)))
        except ValidationError:
            continue
    chosen = select_nickname([nickname for _, nickname in parsed])
    return next((index for index, n in parsed if n is chosen), None)


def merge_with_current_person(payload: Entry, current: Entry) -> Entry:
    """Return ``payload`` with the values it does not own kept from ``current``.

    Only fields the payload carries are merged, and a field leaves it only when
    its policy leaves Google's value untouched. ``payload`` itself is left
    untouched.
    """
    merged: Entry = {}
    for field, pushed in payload.items():
        policy = FIELD_POLICIES.get(field)
        if policy is None:
            logger.warning("Pushed Google field has no merge policy", field=field)
            merged[field] = pushed
            continue
        result = policy.merge(pushed, current.get(field) or [])
        if result is not Omit.FIELD:
            merged[field] = result
    return merged


def _is_contact_entry(entry: dict[str, Any]) -> bool:
    """Whether an entry belongs to the contact rather than a linked profile."""
    source_type = (entry.get("metadata") or {}).get("source", {}).get("type")
    return source_type not in _PROFILE_SOURCE_TYPES


def _writable(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry without its output-only parts."""
    return {key: value for key, value in entry.items() if key not in _OUTPUT_ONLY_KEYS}


def _merge_names(
    pushed: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Add the current name's honorifics and phonetic parts to the pushed name."""
    if not pushed or not current:
        return pushed
    owned = next(
        (name for name in current if (name.get("metadata") or {}).get("primary")),
        current[0],
    )
    if not _is_contact_entry(owned):
        return pushed
    preserved = {
        key: value for key, value in owned.items() if key in _PRESERVED_NAME_KEYS
    }
    return [{**pushed[0], **preserved}, *pushed[1:]]


def _merge_events(
    pushed: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append the current events of every type the local contact does not own."""
    kept = [
        _writable(event)
        for event in current
        if _is_contact_entry(event)
        and str(event.get("type") or "").lower() not in _OWNED_EVENT_TYPES
    ]
    return [*pushed, *kept]


def _merge_organizations(
    pushed: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Write the pushed organization over the owned one, keeping the others."""
    if not pushed or not current:
        return pushed
    owned_index = next(
        (index for index, org in enumerate(current) if org.get("current") is True),
        0,
    )
    owned = current[owned_index]
    merged: list[dict[str, Any]] = []
    if not _is_contact_entry(owned):
        merged.append(pushed[0])
    for index, org in enumerate(current):
        if not _is_contact_entry(org):
            continue
        if index == owned_index:
            kept = {
                key: value
                for key, value in _writable(org).items()
                if key not in _OWNED_ORGANIZATION_KEYS
            }
            merged.append({**kept, **pushed[0]})
        else:
            merged.append(_writable(org))
    return [*merged, *pushed[1:]]


FIELD_POLICIES: Final[Mapping[str, FieldPolicy]] = {
    "names": MergedBy(_merge_names),
    "nicknames": KeepUnchosen(_chosen_nickname),
    "emailAddresses": KeepUnimported(_imported_by(GoogleEmailAddress, import_email)),
    "phoneNumbers": KeepUnimported(_imported_by(GooglePhoneNumber, import_phone)),
    "addresses": KeepUnimported(_imported_by(GoogleAddress, import_address)),
    "biographies": WhollyOwned("inbound imports every biography as a note"),
    "organizations": MergedBy(_merge_organizations),
    "memberships": WhollyOwned(
        "the push rebuilds reserved groups, starred and every tag's group (#1821)"
    ),
    "birthdays": SingletonLeaveUnimported(
        _imported_by(GoogleBirthday, import_birthday)
    ),
    "events": MergedBy(_merge_events),
}
