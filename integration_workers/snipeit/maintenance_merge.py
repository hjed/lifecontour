"""Per-field three-way merge of a maintenance journal with its Snipe-IT record (#1898).

A maintenance journal is pushed as the five fields of a Snipe-IT maintenance
record, each reconciled on its own (``field_merge``) against the base the
record's sync row records (``reference_data.synced_entries``).

Fields are compared in the shape a push sends them (``reverse_transform``, and
``_snipeit_record_payload`` for a fetched record): text as typed, Snipe-IT's
maintenance type, dates as local ``YYYY-MM-DD``. Each is keyed as a journal
imported from it holds it (``SnipeItMaintenanceTransformer.as_imported``), so
what an import fills in never reads as an edit. Nothing here does I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from core_shared.sync_base import SyncedEntries, entry_key, parse_reference_data

from field_merge import FieldMerge, base_after_push, complete_base, reconcile
from snipeit_maintenance_transformer import SnipeItMaintenanceTransformer

type MaintenanceField = Literal[
    "name", "notes", "asset_maintenance_type", "start_date", "completion_date"
]

MAINTENANCE_FIELDS: Final[tuple[MaintenanceField, ...]] = (
    "name",
    "notes",
    "asset_maintenance_type",
    "start_date",
    "completion_date",
)

# ``reference_data`` key of the values a pull's queued event brings in.
QUEUED_ENTRIES_KEY: Final = "queued_entries"

type Payload = Mapping[str, Any]
type Base = dict[MaintenanceField, frozenset[str]]


def base_of(payload: Payload) -> Base:
    """The base a payload makes: one key per field; ``None`` is a value too."""
    imported = SnipeItMaintenanceTransformer.as_imported(payload)
    return {
        field: frozenset({entry_key(imported.get(field))})
        for field in MAINTENANCE_FIELDS
    }


def effective_base(
    synced: Base, queued: SyncedEntries | None, *, local: Payload
) -> Base:
    """The base a merge uses while a pull's event may still be queued.

    A pull hands its changes to the journal through the outbox, so the journal
    takes them some time after the pull. A field the pull queued is agreed once
    the journal holds the queued value; until then the recorded base stands.
    """
    held = base_of(local)
    queued = queued or {}
    return {
        field: queued[field]
        if field in queued and queued[field] == held[field]
        else keys
        for field, keys in synced.items()
    }


def push_base(recorded: SyncedEntries | None, *, remote: Payload) -> Base:
    """The base a push merges against.

    A field the row does not record (one synced before bases existed) takes
    the remote as its base, so local's value is sent wherever it differs, as
    every field was before. The events carry no old values to do better with.
    """
    return complete_base(recorded, base_of(remote))


def pull_base(
    recorded: SyncedEntries | None, queued: SyncedEntries, *, local: Payload
) -> Base:
    """The base a pull merges against: the effective base (``effective_base``).

    A field the row does not record takes local as its base, so the remote
    wins it, as every field did before bases existed.
    """
    return effective_base(complete_base(recorded, base_of(local)), queued, local=local)


def recorded_queued_entries(reference_data: str | None) -> SyncedEntries:
    """The values a sync row records a pull as having queued; none if unreadable."""
    queued = parse_reference_data(reference_data).get(QUEUED_ENTRIES_KEY)
    if not isinstance(queued, dict):
        return {}
    return {
        field: frozenset(keys)
        for field, keys in queued.items()
        if isinstance(keys, list) and all(isinstance(key, str) for key in keys)
    }


def queued_by(
    *, local: Payload, remote: Payload, kept: frozenset[MaintenanceField]
) -> Base:
    """The values a pull's event changes the journal to: the remote's, for
    each field the journal does not keep and does not already hold."""
    held, remote_keys = base_of(local), base_of(remote)
    return {
        field: remote_keys[field]
        for field in MAINTENANCE_FIELDS
        if field not in kept and remote_keys[field] != held[field]
    }


def merge(
    base: Base, *, local: Payload, remote: Payload
) -> FieldMerge[MaintenanceField]:
    """Reconcile every field of a journal with its record, against ``base``.

    The dates are one range: when taking one from each side would put the
    start after the end, both take local's (local wins, as in a conflict).
    """
    merged = reconcile(base, local=base_of(local), remote=base_of(remote))
    dates: frozenset[MaintenanceField] = frozenset({"start_date", "completion_date"})
    if len(dates & merged.local_fields) != 1:
        return merged
    imported_local = SnipeItMaintenanceTransformer.as_imported(local)
    imported_remote = SnipeItMaintenanceTransformer.as_imported(remote)
    start, end = (
        (imported_local if field in merged.local_fields else imported_remote).get(field)
        for field in ("start_date", "completion_date")
    )
    if not (start and end and start > end):
        return merged
    return FieldMerge(merged.local_fields | dates, merged.remote_fields - dates)


def base_after(base: Base, *, local: Payload, after: Payload) -> Base:
    """The base a push leaves (``field_merge.base_after_push``)."""
    return base_after_push(base, local=base_of(local), after=base_of(after))


def payload_for(fields: frozenset[MaintenanceField], local: Payload) -> dict[str, Any]:
    """The PATCH body for the fields local owns; a cleared field is sent null."""
    return {field: local.get(field) for field in MAINTENANCE_FIELDS if field in fields}
