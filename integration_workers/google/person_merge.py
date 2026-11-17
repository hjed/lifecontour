"""Merge a contact push into the Google person as it stands.

A push names fields in ``updatePersonFields`` and Google replaces each named
field wholesale, while the payload is built from the local contact alone. The
merge folds back the values of those fields the local model does not own, so a
push changes only what the local contact can represent (#1732).

The local contact owns exactly what inbound sync (``transformer.py``) imports,
and the merge asks the import itself: an entry its per-entry functions reject
(an address with no country code, an invalid email, a text-only birthday) is
one local never held, so the push keeps it (#1788).

Importable is not the same as held, though: an email added in Google since the
last pull is importable, but the contact has never seen it. So the emails,
phones, addresses and birthdays merge three ways against the *synced base* -
the keys of the entries the last sync agreed both sides held, recorded on the
link (``synced_entries``, ``core_shared.sync_base``). An entry Google gained
since the base is kept, one deleted locally is dropped, and one Google deleted
or edited is not pushed back over it; a push that leaves Google holding what
local does not reports ``pending_import``, so the next pull imports it (#1861).

Every field a push can send has a policy in ``FIELD_POLICIES``;
``tests/unit/test_push_field_ownership.py`` fails when one is added without.
Values held by a person's profile rather than the contact itself are never
copied into the contact.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Literal, Protocol

import structlog
from core_shared.sync_base import (
    SyncedEntries,
    remote_unchanged_since_sync,
    three_way_entries,
)
from pydantic import ValidationError

from api_models import GoogleNickname
from synced_entries import (
    BASE_FIELDS,
    BaseField,
    Keys,
    raw_entry_keys,
    raw_synced_entries,
)
from transformer import imported_organization_index, select_nickname

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


@dataclass(frozen=True)
class SyncContext:
    """What a push merges against: the synced base and the address fallback."""

    base: SyncedEntries
    address_fallback_country: str | None

    def base_of(self, field: BaseField) -> frozenset[str]:
        """The field's base keys; a field never recorded has none."""
        return self.base.get(field, frozenset())

    def keys_of(self, field: BaseField) -> Callable[[Entry], Keys]:
        """The keys of a raw entry of ``field``, none when inbound skips it."""
        return lambda entry: raw_entry_keys(field, entry, self.address_fallback_country)


@dataclass(frozen=True)
class FieldMerge:
    """A field's merged value, with what Google keeps that local does not hold.

    ``kept`` is the keys of importable entries kept from Google, ``suppressed``
    those of local entries held back because Google deleted or edited them,
    and ``remote_won`` whether Google now holds anything local does not.
    """

    value: Merged
    kept: frozenset[str] = frozenset()
    suppressed: frozenset[str] = frozenset()
    remote_won: bool = False


class FieldPolicy(Protocol):
    """How one pushed field merges into the field as Google holds it."""

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        """The value to send, or ``Omit.FIELD`` to leave Google's untouched."""
        ...


@dataclass(frozen=True)
class KeepUnsynced:
    """A list local owns only as far as the base: a three-way merge by key.

    Entries inbound does not import are kept, as local never held them -
    unless the push sends the same entry, which Google would then hold twice.
    A profile's entries count as Google's, since inbound imports them too, but
    are never copied into the contact.
    """

    field: BaseField

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        keys = sync.keys_of(self.field)
        pushed_keys = [keys(entry) for entry in pushed]
        remote_keys = [keys(entry) for entry in current]
        decision = three_way_entries(
            base=sync.base_of(self.field), local=pushed_keys, remote=remote_keys
        )
        sent = [
            entry
            for index, entry in enumerate(pushed)
            if index not in decision.suppressed
        ]
        kept = [
            _writable(entry)
            for index, entry in enumerate(current)
            if _is_contact_entry(entry)
            and (
                index in decision.kept
                or (
                    not remote_keys[index] and not any(_is_echo(entry, p) for p in sent)
                )
            )
        ]
        return FieldMerge(
            [*sent, *kept],
            kept=frozenset().union(*(remote_keys[i] for i in decision.kept)),
            suppressed=frozenset().union(
                *(pushed_keys[i] for i in decision.suppressed)
            ),
            remote_won=decision.remote_won,
        )


@dataclass(frozen=True)
class SingletonUnsynced:
    """A field Google holds once per contact, such as the birthday.

    Google cannot hold a kept entry beside a pushed one, so the field leaves
    the update mask whenever Google's entry should stand: one inbound never
    imported, one added in Google since the base, or one edited or deleted
    there while the local value is unchanged. Otherwise the pushed value wins.
    A profile's entry is never written, but one gained since the base is still
    owed to the next pull, which imports it.
    """

    field: BaseField

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        keys = sync.keys_of(self.field)
        base = sync.base_of(self.field)
        contact_entries = [entry for entry in current if _is_contact_entry(entry)]
        remote: Keys = frozenset().union(*map(keys, contact_entries))
        profile: Keys = frozenset().union(
            *(keys(entry) for entry in current if not _is_contact_entry(entry))
        )
        pushed_keys: Keys = keys(pushed[0]) if pushed else frozenset()
        # Not the contact's until a pull imports it, so never part of a base.
        gained = profile - base - pushed_keys
        if not pushed:
            if contact_entries and not remote:
                return FieldMerge(Omit.FIELD, kept=gained, remote_won=bool(gained))
            if remote - base:
                return FieldMerge(Omit.FIELD, remote_won=True)
            return FieldMerge(pushed, kept=gained, remote_won=bool(gained))
        if pushed_keys & base and not remote & base:
            # Local still holds the base value, which Google edited or deleted.
            return FieldMerge(Omit.FIELD, remote_won=True)
        return FieldMerge(pushed, kept=gained, remote_won=bool(gained))


@dataclass(frozen=True)
class KeepUnchosen:
    """Inbound reads one entry, which local owns; the others are kept beside it.

    The pushed entry leads the list, so it is the one inbound and the next push
    choose. With nothing pushed every entry goes: inbound would read a survivor
    as the contact's own, undoing the local clear on the next pull.
    """

    choose: Callable[[list[Entry]], int | None]

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        if not pushed:
            return FieldMerge(pushed)
        owned = self.choose(current)
        kept = [
            _writable(entry)
            for index, entry in enumerate(current)
            if index != owned and _is_contact_entry(entry)
        ]
        return FieldMerge([*pushed, *kept])


@dataclass(frozen=True)
class MergedBy:
    """A field whose owned entry keeps parts of Google's (names, organizations)."""

    merge_entries: Callable[[list[Entry], list[Entry]], list[Entry]]

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        return FieldMerge(self.merge_entries(pushed, current))


@dataclass(frozen=True)
class OwnedOrganization:
    """The organization inbound imports is the contact's company and job title.

    A pushed company merges into it as :func:`_merge_organizations` does,
    unless local still holds the base value and Google edited or deleted it
    since. With nothing pushed, the base tells a company cleared locally (in
    the base: the organization goes, the others stay) from one Google added
    since the last sync (kept, and owed to the next pull). A profile's
    organization cannot be cleared, so the pull imports it again.
    """

    field: Literal["organizations"] = "organizations"

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        keys = sync.keys_of(self.field)
        base = sync.base_of(self.field)
        index = _imported_organization(current)
        owned = None if index is None else current[index]
        remote: Keys = frozenset() if owned is None else keys(owned)
        if pushed:
            if keys(pushed[0]) & base and not remote & base:
                return FieldMerge(Omit.FIELD, remote_won=True)
            return FieldMerge(_merge_organizations(pushed, current))
        if owned is None or not remote:
            return FieldMerge(Omit.FIELD)
        if not remote & base or not _is_contact_entry(owned):
            return FieldMerge(Omit.FIELD, remote_won=True)
        others = [org for position, org in enumerate(current) if position != index]
        # Whichever of the others inbound reads next is Google's, not local's.
        kept: Keys = frozenset().union(*map(keys, others))
        return FieldMerge(
            [_writable(org) for org in others if _is_contact_entry(org)],
            kept=kept,
            remote_won=bool(kept),
        )


@dataclass(frozen=True)
class OwnedBiographies:
    """Inbound imports every biography as a note, so local owns them all.

    Pushed notes replace Google's, unless local holds exactly the base notes
    and Google edited them since. With no notes pushed, the base tells notes
    cleared locally (all in the base: cleared) from one Google added since
    (kept, and owed to the next pull). A profile's biography cannot be
    cleared, so the pull imports it again.
    """

    field: Literal["biographies"] = "biographies"

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        keys = sync.keys_of(self.field)
        base = sync.base_of(self.field)
        contact = [bio for bio in current if _is_contact_entry(bio)]
        remote: Keys = frozenset().union(*map(keys, contact))
        profile: Keys = frozenset().union(
            *(keys(bio) for bio in current if not _is_contact_entry(bio))
        )
        local: Keys = frozenset().union(*map(keys, pushed))
        if pushed:
            if local and local == base and remote != base:
                return FieldMerge(Omit.FIELD, remote_won=True)
            return FieldMerge(pushed)
        if not remote - base:
            if not contact:
                return FieldMerge(Omit.FIELD, remote_won=bool(profile))
            return FieldMerge([], kept=profile, remote_won=bool(profile))
        return FieldMerge(Omit.FIELD, remote_won=True)


@dataclass(frozen=True)
class WhollyOwned:
    """Local holds every entry inbound imports, and inbound imports them all."""

    reason: str

    def merge(
        self, pushed: list[Entry], current: list[Entry], sync: SyncContext
    ) -> FieldMerge:
        return FieldMerge(pushed)


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


@dataclass(frozen=True)
class PushMerge:
    """A merged push payload, and what it leaves Google holding beyond local.

    * ``kept`` — per base field, the keys of importable entries kept from
      Google that local does not hold: never part of the next base.
    * ``suppressed`` — per base field, the keys of local entries held back
      because Google deleted or edited them: still local's, so part of the
      next base, and a second push before the pull holds them back again.
    * ``pending_import`` — Google now holds something local does not, so the
      next pull must import it even though the etag will be the push's own.
    * ``merged_fields`` — the base fields the update sends; a field it leaves
      out keeps its previous base.
    """

    payload: Entry
    kept: Mapping[BaseField, frozenset[str]]
    suppressed: Mapping[BaseField, frozenset[str]]
    pending_import: bool
    merged_fields: frozenset[BaseField]


# The base fields every push sent while they were loaded, empty included, from
# before they were in a base: an unchanged etag shows local held their values.
_ALWAYS_SENT_FIELDS: Final[frozenset[BaseField]] = frozenset(
    {"emailAddresses", "phoneNumbers", "addresses", "birthdays"}
)


def resolve_synced_base(
    recorded: SyncedEntries | None,
    current: Entry,
    *,
    synced_version: str | None,
    address_fallback_country: str | None = None,
) -> SyncedEntries:
    """The base a push merges against.

    The link's recorded base when it has one. A field it lacks - the whole
    base for a link from before bases were recorded, or a field that joined
    the base since (#1938) - gets an empty base, which keeps every Google
    entry: nothing tells an addition there from a local deletion. A field
    every push always sent falls back on the etag instead: a person unchanged
    since the last sync is its own base. Organizations and biographies do not,
    as an older push left them out when local held none, so an unchanged etag
    can be that push's own over a value local never imported.

    The empty base is recorded as such, so a push that leaves the field out
    keeps it rather than reading its own etag as unchanged.
    """
    recorded = recorded or {}
    missing = [field for field in BASE_FIELDS if field not in recorded]
    if not missing:
        return recorded
    own: SyncedEntries = (
        raw_synced_entries(current, address_fallback_country)
        if remote_unchanged_since_sync(synced_version, current.get("etag"))
        else {}
    )
    return {
        **recorded,
        **{
            field: (
                own.get(field, frozenset())
                if field in _ALWAYS_SENT_FIELDS
                else frozenset()
            )
            for field in missing
        },
    }


def merge_for_push(
    payload: Entry,
    current: Entry,
    *,
    synced_base: SyncedEntries | None = None,
    address_fallback_country: str | None = None,
) -> PushMerge:
    """Merge ``payload`` into ``current``, three ways against ``synced_base``.

    Only fields the payload carries are merged, and a field leaves it only when
    its policy leaves Google's value untouched. ``payload`` itself is left
    untouched.

    ``synced_base`` None means ``current`` is the person as last synced, so it
    is its own base. ``address_fallback_country`` is the country the last
    applied pull gave addresses with none, as the link records it, so a
    countryless address is keyed as that pull imported it (#1820). What the
    import would infer *now* is not used.
    """
    sync = SyncContext(
        base=(
            raw_synced_entries(current, address_fallback_country)
            if synced_base is None
            else synced_base
        ),
        address_fallback_country=address_fallback_country,
    )
    merged: Entry = {}
    kept: dict[BaseField, frozenset[str]] = {}
    suppressed: dict[BaseField, frozenset[str]] = {}
    pending_import = False
    for field, pushed in payload.items():
        policy = FIELD_POLICIES.get(field)
        if policy is None:
            logger.warning("Pushed Google field has no merge policy", field=field)
            merged[field] = pushed
            continue
        result = policy.merge(pushed, current.get(field) or [], sync)
        pending_import = pending_import or result.remote_won
        if result.value is Omit.FIELD:
            continue
        merged[field] = result.value
        if isinstance(policy, _BASED_POLICIES):
            kept[policy.field] = result.kept
            suppressed[policy.field] = result.suppressed
    # A field the payload leaves out - one this push did not load, as every
    # owned field is sent once loaded - keeps Google's value unmerged, which
    # local may lack. The pulls older than this push are skipped (#1938), so
    # the next pull must import it.
    pending_import = pending_import or any(
        current.get(field) for field in FIELD_POLICIES if field not in payload
    )
    return PushMerge(
        payload=merged,
        kept=kept,
        suppressed=suppressed,
        pending_import=pending_import,
        merged_fields=frozenset(kept),
    )


def merge_with_current_person(
    payload: Entry,
    current: Entry,
    *,
    address_fallback_country: str | None = None,
    synced_base: SyncedEntries | None = None,
) -> Entry:
    """The merged payload alone; see :func:`merge_for_push`."""
    return merge_for_push(
        payload,
        current,
        synced_base=synced_base,
        address_fallback_country=address_fallback_country,
    ).payload


def _is_contact_entry(entry: dict[str, Any]) -> bool:
    """Whether an entry belongs to the contact rather than a linked profile."""
    source_type = (entry.get("metadata") or {}).get("source", {}).get("type")
    return source_type not in _PROFILE_SOURCE_TYPES


def _is_echo(current: Entry, pushed: Entry) -> bool:
    """Whether Google's ``current`` entry is ``pushed`` as Google holds it.

    Compared on the parts the push writes: Google adds its own (a formatted
    value, a country name) and both sides carry metadata.
    """
    held = _writable(current)
    return all(
        held.get(part) == value
        for part, value in pushed.items()
        if part not in _OUTPUT_ONLY_KEYS
    )


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
    owned_index = _imported_organization(current)
    if not pushed or owned_index is None:
        return pushed
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


def _imported_organization(current: list[Entry]) -> int | None:
    """The index of the organization inbound reads into the contact."""
    return imported_organization_index([org.get("current") for org in current])


# The policies that merge against the synced base and record it.
_BASED_POLICIES: Final = (
    KeepUnsynced,
    SingletonUnsynced,
    OwnedOrganization,
    OwnedBiographies,
)

FIELD_POLICIES: Final[Mapping[str, FieldPolicy]] = {
    "names": MergedBy(_merge_names),
    "nicknames": KeepUnchosen(_chosen_nickname),
    "emailAddresses": KeepUnsynced("emailAddresses"),
    "phoneNumbers": KeepUnsynced("phoneNumbers"),
    "addresses": KeepUnsynced("addresses"),
    "biographies": OwnedBiographies(),
    "organizations": OwnedOrganization(),
    "memberships": WhollyOwned(
        "the push rebuilds reserved groups, starred and every tag's group (#1821)"
    ),
    "birthdays": SingletonUnsynced("birthdays"),
    "events": MergedBy(_merge_events),
}
