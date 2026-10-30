"""The base an Immich person push merges ``name`` and ``birthDate`` against (#1900).

The push used to PUT the local name and birthday as they stood, so a name or
birthday edited in Immich since the last pull was overwritten by the next local
edit. With the base - what both sides agreed on at the last sync, recorded per
field as ``core_shared.sync_base`` keys - each field is merged three ways:

* changed only in Immich: not sent, so Immich keeps it;
* changed only locally: sent;
* changed on both sides: sent - the push follows a local edit, the newest
  intent, and only this way does a name the pull never imports converge.

A birthday the push leaves in Immich unimported marks the link
``pending_import`` so the next pull imports it. A name never does: the pull
imports a name only when it creates the contact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

import structlog
from core_shared.sync_base import (
    SyncedEntries,
    Winner,
    entry_key,
    remote_unchanged_since_sync,
    three_way_value,
)

from immich_models import ImmichPerson

logger = structlog.get_logger(__name__)

type PersonBaseField = Literal["name", "birthDate"]
type Keys = frozenset[str]
type PersonBase = dict[PersonBaseField, Keys]

_NO_KEYS: Final[Keys] = frozenset()


def parse_birth_date(birth_date: str | None) -> tuple[int, int, int] | None:
    """Parse an ISO-8601 date string into ``(year, month, day)``, or ``None``."""
    if not birth_date:
        return None
    try:
        dt = datetime.strptime(birth_date, "%Y-%m-%d")  # noqa: DTZ007
    except ValueError:
        logger.warning("Invalid birth date format", birth_date=birth_date)
        return None
    return (dt.year, dt.month, dt.day)


def name_keys(name: str | None) -> Keys:
    """The name's key, ignoring whitespace but not case, or none when blank.

    Case counts, so a local fix of a name's case is still pushed.
    """
    normalised = " ".join((name or "").split())
    if not normalised:
        return _NO_KEYS
    return frozenset({entry_key("name", normalised)})


def birth_date_keys(birth_date: str | None) -> Keys:
    """The birthday's key, from the date it names, or none without one.

    One Immich holds but that cannot be read is keyed as written, so it still
    differs from every readable date.
    """
    if not birth_date:
        return _NO_KEYS
    parsed = parse_birth_date(birth_date)
    if parsed is None:
        return frozenset({entry_key("birthDate", "unreadable", birth_date)})
    return frozenset({entry_key("birthDate", *parsed)})


def _keys_of(person: ImmichPerson, field: PersonBaseField) -> Keys:
    if field == "name":
        return name_keys(person.name)
    return birth_date_keys(person.birth_date)


def person_entries(person: ImmichPerson) -> PersonBase:
    """The keys of both fields as ``person`` holds them."""
    return {
        "name": _keys_of(person, "name"),
        "birthDate": _keys_of(person, "birthDate"),
    }


def resolve_base(
    recorded: SyncedEntries | None,
    current: ImmichPerson,
    *,
    recorded_version: str | None,
    current_version: str,
) -> SyncedEntries:
    """The base a push merges against.

    The link's recorded base when it has one. A link from before bases falls
    back on the version: a person unchanged since the last sync is its own
    base, and a changed one gets an empty base - nothing tells which side
    changed it.
    """
    if recorded is not None:
        return recorded
    if remote_unchanged_since_sync(recorded_version, current_version):
        return dict(person_entries(current).items())
    return {}


@dataclass(frozen=True)
class PushOutcome:
    """What the link records after a push.

    * ``base`` — the base the next push merges against.
    * ``pending_import`` — Immich holds a birthday local does not, for the
      next pull to import.
    """

    base: PersonBase
    pending_import: bool


@dataclass(frozen=True)
class PushPlan:
    """What a push sends, and how to read what Immich kept after it.

    * ``update_data`` — the fields to PUT, in Immich's names.
    * ``local_keys`` — the keys of each field local holds, absent for one it
      holds none of (no name, or no full-precision birthday).
    * ``merged_base`` — the base the push merged against.
    """

    update_data: dict[str, str]
    local_keys: PersonBase
    merged_base: SyncedEntries

    def settle(self, response: ImmichPerson) -> PushOutcome:
        """The base and marker to record, given the person Immich now holds.

        Read from the response, not the person fetched before the PUT, so a
        field Immich changed in between is not taken as agreed. A field both
        sides now hold the same takes its base from the response. Every other
        field keeps the base the push merged against, so a second push before
        the pull holds back again; a birthday among them that Immich holds
        differently is left for the pull to import.
        """
        base: PersonBase = {}
        for field in ("name", "birthDate"):
            held = _keys_of(response, field)
            if self.local_keys.get(field) == held:
                base[field] = held
            elif field in self.merged_base:
                base[field] = self.merged_base[field]
        # A base without a birthday reads as agreeing on none: an Immich
        # person still without one leaves nothing to import.
        birthday = _keys_of(response, "birthDate")
        return PushOutcome(
            base=base,
            pending_import=self.local_keys.get("birthDate") != birthday
            and birthday != self.merged_base.get("birthDate", _NO_KEYS),
        )


def plan_push(
    *,
    local_name: str | None,
    local_birth_date: str | None,
    current: ImmichPerson,
    base: SyncedEntries,
) -> PushPlan:
    """Merge the local name and birthday into ``current`` three ways.

    A local field that is ``None`` (no name, or no full-precision birthday)
    is never sent: Immich keeps its own.
    """
    local: dict[PersonBaseField, str | None] = {
        "name": local_name,
        "birthDate": local_birth_date,
    }
    local_keys: PersonBase = {}
    update_data: dict[str, str] = {}

    for field, value in local.items():
        if value is None:
            continue
        local_keys[field] = (
            name_keys(value) if field == "name" else birth_date_keys(value)
        )
        winner = three_way_value(
            base=base.get(field),
            local=local_keys[field],
            remote=_keys_of(current, field),
        )
        if winner in (Winner.LOCAL, Winner.CONFLICT):
            update_data[field] = value

    return PushPlan(update_data=update_data, local_keys=local_keys, merged_base=base)
