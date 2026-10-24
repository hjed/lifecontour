"""The synced base an outbound push merges against (#1861).

A push that merges local values into the remote record as it stands cannot
tell, on its own, an entry the remote *gained* since the last sync from one the
local side *deleted*: both are "in the remote, not in local". The difference is
the base — what both sides agreed on at the last sync. With it, a push becomes a
three-way merge: an entry the remote gained is kept, one local deleted is
dropped, and a remote edit to something local left alone wins.

The base lives on the integration link (``sync_metadata.reference_data``) as
opaque keys per field, written by every applied pull and every push. Keys are
hashed so the link holds no copy of the values. When a push keeps something the
local side does not hold, it marks the link ``pending_import`` so the next pull
applies that record even though its version is the push's own.

Nothing here knows an integration's fields. A list field (a contact's emails)
compares key sets with :func:`three_way_keys`; a scalar (an asset's serial)
compares values with :func:`three_way_value`, and entries written several ways
(a phone in E.164 or as typed) carry a key per spelling for
:func:`three_way_entries`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

# ``reference_data`` key: per field, the keys of the entries both sides held at
# the last sync.
SYNCED_ENTRIES_KEY: Final = "synced_entries"

# ``reference_data`` key: a push kept remote entries the local side does not
# hold, so the next pull must apply the record even with an unchanged version.
PENDING_IMPORT_KEY: Final = "pending_import"

# Half a SHA-256 tells entries of one record apart with room to spare.
_KEY_LENGTH: Final = 32

type SyncedEntries = Mapping[str, frozenset[str]]


def entry_key(*parts: object) -> str:
    """An opaque, stable key for one entry, from the parts that identify it.

    Pass only the parts that make the entry *that* entry — its value, not its
    label or position — so a relabelled entry is still recognised.
    """
    canonical = json.dumps(
        list(parts), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:_KEY_LENGTH]


def parse_reference_data(reference_data: str | None) -> dict[str, Any]:
    """A link's ``reference_data`` as a dict; anything unreadable is empty."""
    if not reference_data:
        return {}
    try:
        parsed = json.loads(reference_data)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def recorded_synced_entries(reference_data: str | None) -> SyncedEntries | None:
    """The base a link records, or ``None`` when it records none.

    A field whose keys cannot be read is left out, so it reads as never synced:
    the reading that keeps the remote's entries rather than deleting them.
    """
    recorded = parse_reference_data(reference_data).get(SYNCED_ENTRIES_KEY)
    if not isinstance(recorded, dict):
        return None
    return {
        field: frozenset(keys)
        for field, keys in recorded.items()
        if isinstance(keys, list) and all(isinstance(key, str) for key in keys)
    }


def serialise_synced_entries[F: str](
    entries: Mapping[F, frozenset[str]],
) -> dict[str, list[str]]:
    """A base as JSON-ready lists, sorted so an unchanged base compares equal.

    Generic in the field type, so a worker can name its fields as a ``Literal``.
    """
    return {field: sorted(keys) for field, keys in entries.items()}


def pending_import(reference_data: str | None) -> bool:
    """Whether a push left entries for the next pull to import."""
    return parse_reference_data(reference_data).get(PENDING_IMPORT_KEY) is True


def remote_unchanged_since_sync(
    recorded_version: str | None, remote_version: str | None
) -> bool:
    """Whether the remote record is still the version the link last synced.

    An unknown version on either side counts as changed.
    """
    return bool(recorded_version) and recorded_version == remote_version


@dataclass(frozen=True)
class ThreeWay:
    """How a pushed list field reconciles with the remote's, given the base.

    * ``kept`` — remote entries to keep: gained remotely since the base.
    * ``dropped`` — remote entries to remove: in the base, deleted locally.
    * ``suppressed`` — local entries not to push: in the base, but gone from
      the remote (deleted or edited there), so the remote's change wins.
    """

    kept: frozenset[str]
    dropped: frozenset[str]
    suppressed: frozenset[str]

    @property
    def remote_won(self) -> bool:
        """The remote holds what local does not: the next pull must import it."""
        return bool(self.kept or self.suppressed)


def three_way_keys(*, base: Set[str], local: Set[str], remote: Set[str]) -> ThreeWay:
    """Reconcile one list field's entry keys against the base.

    An entry on both sides is pushed once and is in none of the sets; one added
    only locally is simply pushed.
    """
    return ThreeWay(
        kept=frozenset(remote - base - local),
        dropped=frozenset((remote & base) - local),
        suppressed=frozenset((local & base) - remote),
    )


@dataclass(frozen=True)
class EntryThreeWay:
    """How a pushed list field's entries reconcile, by position.

    * ``kept`` — indices of remote entries to keep: gained remotely since the
      base, and not held locally.
    * ``suppressed`` — indices of local entries not to push: in the base, but
      gone from the remote, so the remote's deletion or edit wins.

    Every other remote entry is either held locally (the local copy is sent)
    or was deleted locally; every other local entry is pushed.
    """

    kept: frozenset[int]
    suppressed: frozenset[int]

    @property
    def remote_won(self) -> bool:
        """The remote holds what local does not: the next pull must import it."""
        return bool(self.kept or self.suppressed)


def three_way_entries(
    *,
    base: Set[str],
    local: Sequence[Set[str]],
    remote: Sequence[Set[str]],
) -> EntryThreeWay:
    """:func:`three_way_keys` for entries that carry several keys.

    An entry that can be written several ways (a phone in E.164 or as typed)
    carries a key per spelling, and two entries are the same entry when any
    of their keys match. An entry with no keys is in neither result.
    """
    local_keys = frozenset().union(*local)
    remote_keys = frozenset().union(*remote)
    return EntryThreeWay(
        kept=frozenset(
            index
            for index, keys in enumerate(remote)
            if keys and not keys & base and not keys & local_keys
        ),
        suppressed=frozenset(
            index
            for index, keys in enumerate(local)
            if keys & base and not keys & remote_keys
        ),
    )


class Winner(Enum):
    """Which side's value a scalar field should end up with."""

    LOCAL = "local"
    REMOTE = "remote"
    SAME = "same"
    CONFLICT = "conflict"


def three_way_value(*, base: object, local: object, remote: object) -> Winner:
    """Reconcile one scalar field against its base value.

    ``CONFLICT`` means both sides changed it differently; the caller's
    integration decides who wins.
    """
    if local == remote:
        return Winner.SAME
    if local == base:
        return Winner.REMOTE
    if remote == base:
        return Winner.LOCAL
    return Winner.CONFLICT
