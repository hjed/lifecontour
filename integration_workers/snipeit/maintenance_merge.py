"""Per-field three-way merge of a maintenance journal with its Snipe-IT record (#1898).

A maintenance journal is pushed as the five fields of a Snipe-IT maintenance
record, each reconciled on its own (``field_merge``) against the base the
record's sync row records (``reference_data.synced_entries``).

Fields are compared in the shape a push sends them (``reverse_transform``, and
``_snipeit_record_payload`` for a fetched record): text as typed, Snipe-IT's
maintenance type, dates as local ``YYYY-MM-DD``. A field the shape leaves out
is ``None``. Nothing here does I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from core_shared.sync_base import SyncedEntries, entry_key

from field_merge import FieldMerge, base_after_push, complete_base, reconcile

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

type Payload = Mapping[str, Any]
type Base = dict[MaintenanceField, frozenset[str]]


def base_of(payload: Payload) -> Base:
    """The base a payload makes: one key per field; ``None`` is a value too."""
    return {
        field: frozenset({entry_key(payload.get(field))})
        for field in MAINTENANCE_FIELDS
    }


def push_base(recorded: SyncedEntries | None, *, remote: Payload) -> Base:
    """The base a push merges against.

    A field the row does not record (one synced before bases existed) takes
    the remote as its base, so local's value is sent wherever it differs, as
    every field was before. The events carry no old values to do better with.
    """
    return complete_base(recorded, base_of(remote))


def pull_base(recorded: SyncedEntries | None, *, local: Payload) -> Base:
    """The base a pull merges against.

    A field the row does not record takes local as its base, so the remote
    wins it, as every field did before bases existed.
    """
    return complete_base(recorded, base_of(local))


def merge(
    base: Base, *, local: Payload, remote: Payload
) -> FieldMerge[MaintenanceField]:
    """Reconcile every field of a journal with its record, against ``base``."""
    return reconcile(base, local=base_of(local), remote=base_of(remote))


def base_after(base: Base, *, local: Payload, after: Payload) -> Base:
    """The base a push leaves (``field_merge.base_after_push``)."""
    return base_after_push(base, local=base_of(local), after=base_of(after))


def payload_for(fields: frozenset[MaintenanceField], local: Payload) -> dict[str, Any]:
    """The PATCH body for the fields local owns; a cleared field is sent null."""
    return {field: local.get(field) for field in MAINTENANCE_FIELDS if field in fields}
