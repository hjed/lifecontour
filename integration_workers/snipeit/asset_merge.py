"""Per-column three-way merge of a gear item with its Snipe-IT asset (#1898).

A gear edit pushes ``name``, ``serial_number`` and ``purchase_date``. Each is
reconciled on its own against the value both sides last agreed on, the base the
asset's link records (``reference_data.synced_entries``, ``core_shared.sync_base``):

* only local changed it — the push sends it, and the pull keeps it until then;
* only Snipe-IT changed it — the push leaves it, and the pull imports it;
* both changed it differently — local wins: it is an edit made here, on purpose.

``model`` and ``manufacturer`` are pull-only: Snipe-IT holds them as references
to other records, so the remote's value always wins.

Values are compared as the import stores them (``normalise_name`` and
``normalise_field``), so a name typed with surrounding spaces matches the one
Snipe-IT gives back. Nothing here does I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal, assert_never

from core_shared.sync_base import SyncedEntries, Winner, entry_key, three_way_value

from snipeit_data_transformer import normalise_field, normalise_name

type PushedColumn = Literal["name", "serial_number", "purchase_date"]

PUSHED_COLUMNS: Final[tuple[PushedColumn, ...]] = (
    "name",
    "serial_number",
    "purchase_date",
)

# The Snipe-IT asset field each pushed column is written to.
SNIPEIT_FIELD: Final[Mapping[PushedColumn, str]] = {
    "name": "name",
    "serial_number": "serial",
    "purchase_date": "purchase_date",
}

type Base = dict[PushedColumn, frozenset[str]]


@dataclass(frozen=True)
class AssetValues:
    """The gear columns one side holds for an asset."""

    name: str
    serial_number: str | None
    purchase_date: date | None
    model: str | None
    manufacturer: str | None

    @classmethod
    def of(cls, source: Any) -> AssetValues:
        """The values a ``gear_items`` row or ``GearItem`` holds."""
        return cls(
            name=source.name,
            serial_number=source.serial_number,
            purchase_date=source.purchase_date,
            model=source.model,
            manufacturer=source.manufacturer,
        )

    def pushed(self, column: PushedColumn) -> object:
        """The value of one pushed column, as held."""
        match column:
            case "name":
                return self.name
            case "serial_number":
                return self.serial_number
            case "purchase_date":
                return self.purchase_date
            case _:
                assert_never(column)

    def comparable(self) -> tuple[object, ...]:
        """Every gear column as an import would store it."""
        return (
            *(_normalised(column, self.pushed(column)) for column in PUSHED_COLUMNS),
            normalise_field(self.model),
            normalise_field(self.manufacturer),
        )


@dataclass(frozen=True)
class PushMerge:
    """What a push sends, and whether Snipe-IT keeps something local lacks.

    * ``send`` — the local value of each column local owns.
    * ``remote_won`` — a column only Snipe-IT changed, left for the pull.
    """

    send: Mapping[PushedColumn, object]
    remote_won: bool


def _normalised(column: PushedColumn, value: object) -> object:
    """One pushed column's value as the import stores it."""
    if value is None:
        return None
    match column:
        case "name":
            return normalise_name(str(value))
        case "serial_number":
            return normalise_field(str(value))
        case "purchase_date":
            return value.isoformat() if isinstance(value, date) else str(value)
        case _:
            assert_never(column)


def column_key(column: PushedColumn, value: object) -> frozenset[str]:
    """The base key of one column's value; ``None`` is a value of its own."""
    return frozenset({entry_key(_normalised(column, value))})


def base_of(values: AssetValues) -> Base:
    """The base a side's values make: one key per pushed column."""
    return {
        column: column_key(column, values.pushed(column)) for column in PUSHED_COLUMNS
    }


def _complete(recorded: SyncedEntries | None, fallback: Base) -> Base:
    """The recorded base, with ``fallback`` for each column it does not record."""
    recorded = recorded or {}
    return {column: recorded.get(column, fallback[column]) for column in PUSHED_COLUMNS}


def push_base(
    recorded: SyncedEntries | None,
    *,
    local: AssetValues,
    remote: AssetValues,
    remote_unchanged: bool,
    changed_fields: Mapping[str, Any],
) -> Base:
    """The base a push merges against.

    A column the link does not record (a link synced before bases existed)
    falls back on the remote when it is still the version last synced. Failing
    that, on what local held before this edit: the old value of a column the
    edit changed, else its current one.
    """
    fallback: Base
    if remote_unchanged:
        fallback = base_of(remote)
    else:
        fallback = {
            column: column_key(
                column,
                changed_fields[column][0]
                if column in changed_fields
                else local.pushed(column),
            )
            for column in PUSHED_COLUMNS
        }
    return _complete(recorded, fallback)


def pull_base(recorded: SyncedEntries | None, *, local: AssetValues) -> Base:
    """The base a pull merges against.

    A column the link does not record takes local as its base, so the remote
    wins it, as every column did before bases existed.
    """
    return _complete(recorded, base_of(local))


def _winner(
    base: Base, column: PushedColumn, local: AssetValues, remote: AssetValues
) -> Winner:
    return three_way_value(
        base=base[column],
        local=column_key(column, local.pushed(column)),
        remote=column_key(column, remote.pushed(column)),
    )


def merge_push(base: Base, *, local: AssetValues, remote: AssetValues) -> PushMerge:
    """Which columns a push sends, reconciled one by one against ``base``."""
    send: dict[PushedColumn, object] = {}
    remote_won = False
    for column in PUSHED_COLUMNS:
        winner = _winner(base, column, local, remote)
        match winner:
            case Winner.LOCAL | Winner.CONFLICT:
                send[column] = local.pushed(column)
            case Winner.REMOTE:
                remote_won = True
            case Winner.SAME:
                pass
            case _:
                assert_never(winner)
    return PushMerge(send=send, remote_won=remote_won)


def merge_pull(base: Base, local: AssetValues, remote: AssetValues) -> AssetValues:
    """The values a pull stores: the remote's, less local edits still to push."""
    kept: dict[PushedColumn, object] = {}
    for column in PUSHED_COLUMNS:
        winner = _winner(base, column, local, remote)
        match winner:
            case Winner.LOCAL | Winner.CONFLICT:
                kept[column] = local.pushed(column)
            case Winner.REMOTE | Winner.SAME:
                kept[column] = remote.pushed(column)
            case _:
                assert_never(winner)
    return AssetValues(
        name=str(kept["name"]),
        serial_number=_optional_str(kept["serial_number"]),
        purchase_date=_optional_date(kept["purchase_date"]),
        model=remote.model,
        manufacturer=remote.manufacturer,
    )


def base_after_push(base: Base, *, local: AssetValues, after: AssetValues) -> Base:
    """The base a push leaves: Snipe-IT's values, where local now holds them.

    A column Snipe-IT still holds otherwise keeps the base the push merged
    against, so the next pull sees local unchanged and imports the remote's
    value, and a second push before it leaves the column alone again.
    """
    return {
        column: (
            after_key
            if (after_key := column_key(column, after.pushed(column)))
            == column_key(column, local.pushed(column))
            else base[column]
        )
        for column in PUSHED_COLUMNS
    }


def holds_other_values(remote: AssetValues, local: AssetValues) -> bool:
    """Whether Snipe-IT holds any gear value local does not."""
    return remote.comparable() != local.comparable()


def payload_for(send: Mapping[PushedColumn, object]) -> dict[str, Any]:
    """The Snipe-IT PATCH body for the columns a push sends.

    A cleared value is sent empty, which Snipe-IT stores as null.
    """
    payload: dict[str, Any] = {}
    for column, value in send.items():
        if value is None:
            payload[SNIPEIT_FIELD[column]] = ""
        elif isinstance(value, date):
            payload[SNIPEIT_FIELD[column]] = value.isoformat()
        else:
            payload[SNIPEIT_FIELD[column]] = value
    return payload


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_date(value: object) -> date | None:
    return value if isinstance(value, date) else None
