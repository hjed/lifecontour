"""The three-way merge of a record's scalar fields, shared by gear and maintenance.

Each side of a field is given as its base keys (``core_shared.sync_base``), so
the record's own module decides how a value is normalised and keyed; this one
only reconciles keys against the base the link records (#1898):

* only local changed a field — local owns it: a push sends it, a pull keeps it;
* only the remote changed it — the remote wins, and the next pull imports it;
* both changed it differently — local wins: it is an edit made here, on purpose.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import assert_never

from core_shared.sync_base import SyncedEntries, Winner, three_way_value

type Keys[F: str] = Mapping[F, frozenset[str]]


@dataclass(frozen=True)
class FieldMerge[F: str]:
    """How a record's fields reconcile.

    * ``local_fields`` — the fields local owns: a push sends them, and a pull
      keeps local's value.
    * ``remote_won`` — a field only the remote changed, for the pull to import.
    """

    local_fields: frozenset[F]
    remote_won: bool


def complete_base[F: str](
    recorded: SyncedEntries | None, fallback: Keys[F]
) -> dict[F, frozenset[str]]:
    """The recorded base, with ``fallback`` for each field it does not record."""
    recorded = recorded or {}
    return {field: recorded.get(field, keys) for field, keys in fallback.items()}


def reconcile[F: str](
    base: Keys[F], *, local: Keys[F], remote: Keys[F]
) -> FieldMerge[F]:
    """Reconcile every field of ``base`` between local and the remote."""
    local_fields: set[F] = set()
    remote_won = False
    for field, base_keys in base.items():
        winner = three_way_value(
            base=base_keys, local=local[field], remote=remote[field]
        )
        match winner:
            case Winner.LOCAL | Winner.CONFLICT:
                local_fields.add(field)
            case Winner.REMOTE:
                remote_won = True
            case Winner.SAME:
                pass
            case _:
                assert_never(winner)
    return FieldMerge(frozenset(local_fields), remote_won)


def base_after_push[F: str](
    base: Keys[F], *, local: Keys[F], after: Keys[F]
) -> dict[F, frozenset[str]]:
    """The base a push leaves: the remote's values, where local now holds them.

    A field the remote still holds otherwise keeps the base the push merged
    against, so the next pull sees local unchanged and imports the remote's
    value, and a second push before it leaves the field alone again.
    """
    return {
        field: after[field] if after[field] == local[field] else base_keys
        for field, base_keys in base.items()
    }
