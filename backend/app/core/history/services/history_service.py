"""Projection of journal and contact domain events into field history rows.

``HistoryService.project_event`` is a *pure* mapping from a single journal/route/
gear or contact domain event (delivered as an :class:`OutboxEvent`) to the list of
:class:`FieldHistoryEntry` rows that should be written for it. It performs no I/O,
so it is trivially unit-testable; the :class:`HistoryProjectionConsumer` owns the
repository and the idempotent writes.

Contacts (ITER12-003 Phase 1): each contact handler reproduces the EXACT rows the
synchronous dual-write (``ContactHistoryService.record_*``) writes today, keyed to
the same ``(entity_type, entity_id)`` pairs the contact aggregation strategy reads
(``contact``/``contact_method``/``contact_address``/``contact_note``/
``contact_important_date``/``contact_relationship``/``contact_summary``). Unlike
journals, contacts spread history across these sub-entity rows, so ``_row`` takes an
explicit ``entity_type``.

Design (ITER12-002 Phase 1):

* Every change is tagged to the *journal* aggregate (``entity_type="journal"``,
  ``entity_id=journal_id``). Route and gear ids are UUIDs, but ``field_history``
  keys on an integer ``entity_id``; grouping route/gear changes under the journal
  (with the route/gear context encoded in ``field_name``) keeps them on the
  integer key, survives route deletion, and needs no join to read back.
* Route/gear events without a ``journal_id`` are skipped rather than raising. The
  ``history-projection`` group reads the stream from id ``0``, so it replays
  historical route/gear events emitted *before* ``journal_id`` enrichment; those
  cannot be attributed to a journal, and gear is many-to-many with journals so a
  plain gear edit has no single parent either.
* Provenance (``source`` + ``changed_by``) and the originating ``event_id`` travel
  in ``event_data`` and are copied onto every row. ``created_at`` is set to
  ``event.occurred_at`` so history reflects when the change happened, not when it
  was projected.
* ``changed_fields`` values arrive as ``[old, new]`` lists after the JSON round
  trip through Redis, so we index positionally rather than unpacking a tuple.
"""

import re
from collections.abc import Sequence
from typing import Any

from core_shared.models.history import Provenance

from app.core.history.models import FieldHistoryEntry
from app.infrastructure.events.outbox_repository import OutboxEvent

_JOURNAL_ENTITY_TYPE = "journal"

# Contact entity types — must match the contact aggregation strategy in
# ``app/core/history/models.py`` and the dual-write's ``record_*`` entity types.
_CONTACT_ENTITY_TYPE = "contact"
_CONTACT_METHOD_ENTITY_TYPE = "contact_method"
_CONTACT_ADDRESS_ENTITY_TYPE = "contact_address"
_CONTACT_NOTE_ENTITY_TYPE = "contact_note"
_CONTACT_IMPORTANT_DATE_ENTITY_TYPE = "contact_important_date"
_CONTACT_RELATIONSHIP_ENTITY_TYPE = "contact_relationship"
_CONTACT_SUMMARY_ENTITY_TYPE = "contact_summary"

# A contact sub-entity field edit publishes ``ContactUpdated`` (the core contact
# event downstream consumers rely on) with a per-sub-entity ``changed_fields`` key
# shaped ``"{prefix}_{sub_id}_{field}"`` (e.g. ``"method_5_value"``). The projection
# decodes that key back to the right sub-entity row, matching the dual-write's
# ``record_method_change`` / ``record_address_change`` / ``record_note_change``.
# Plain keys (``first_name``, ``status``, …) belong to the contact itself.
_SUBENTITY_FIELD_RE = re.compile(r"^(method|address|note)_(\d+)_(.+)$")
_SUBENTITY_PREFIX_ENTITY_TYPE = {
    "method": _CONTACT_METHOD_ENTITY_TYPE,
    "address": _CONTACT_ADDRESS_ENTITY_TYPE,
    "note": _CONTACT_NOTE_ENTITY_TYPE,
}


class HistoryService:
    """Maps journal and contact domain events to field-history rows."""

    def project_event(self, event: OutboxEvent) -> list[FieldHistoryEntry]:
        """Return the history rows for ``event`` (empty for irrelevant events)."""
        data = event.event_data or {}
        handler = _HANDLERS.get(event.event_type)
        if handler is None:
            return []
        return handler(self, event, data)

    # -- per-event-type handlers --------------------------------------------

    def _project_journal_created(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        journal_id = data["journal_id"]
        return [
            self._row(
                event,
                data,
                entity_id=journal_id,
                field_name="__created__",
                old_value=None,
                new_value=data.get("title"),
            )
        ]

    def _project_journal_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        journal_id = data["journal_id"]
        return self._rows_from_changed_fields(
            event, data, entity_id=journal_id, changed_fields=data.get("changed_fields")
        )

    def _project_journal_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        journal_id = data["journal_id"]
        return [
            self._row(
                event,
                data,
                entity_id=journal_id,
                field_name="__deleted__",
                old_value=None,
                new_value=None,
            )
        ]

    def _project_journal_type_added(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return [
            self._row(
                event,
                data,
                entity_id=data["journal_id"],
                field_name="types",
                old_value=None,
                new_value=data.get("journal_type"),
            )
        ]

    def _project_journal_type_removed(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return [
            self._row(
                event,
                data,
                entity_id=data["journal_id"],
                field_name="types",
                old_value=data.get("journal_type"),
                new_value=None,
            )
        ]

    def _project_route_created(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        route_id = data["route_id"]
        journal_id = data.get("journal_id")
        if journal_id is None:
            return []
        return [
            self._row(
                event,
                data,
                entity_id=journal_id,
                field_name=f"route:{route_id}:__created__",
                old_value=None,
                new_value=data.get("name"),
            )
        ]

    def _project_route_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        route_id = data["route_id"]
        journal_id = data.get("journal_id")
        if journal_id is None:
            return []
        return self._rows_from_changed_fields(
            event,
            data,
            entity_id=journal_id,
            changed_fields=data.get("changed_fields"),
            field_prefix=f"route:{route_id}:",
        )

    def _project_route_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        route_id = data["route_id"]
        journal_id = data.get("journal_id")
        if journal_id is None:
            return []
        return [
            self._row(
                event,
                data,
                entity_id=journal_id,
                field_name=f"route:{route_id}:__deleted__",
                old_value=None,
                new_value=None,
            )
        ]

    def _project_gear_item_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        journal_id = data.get("journal_id")
        if journal_id is None:
            return []
        gear_item_id = data["gear_item_id"]
        return self._rows_from_changed_fields(
            event,
            data,
            entity_id=journal_id,
            changed_fields=data.get("changed_fields"),
            field_prefix=f"gear:{gear_item_id}:",
        )

    # -- contact handlers (ITER12-003 Phase 1) -------------------------------

    def _project_contact_created(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        # Only the contact-level "created" marker comes from ContactCreated. The
        # per-sub-entity "created" markers come from the ContactMethodAdded /
        # ContactAddressAdded / ContactNoteAdded / ImportantDateAdded events that
        # the bulk save publishes alongside, so they are not duplicated here.
        return [
            self._row(
                event,
                data,
                entity_type=_CONTACT_ENTITY_TYPE,
                entity_id=data["contact_id"],
                field_name="status",
                old_value=None,
                new_value="created",
            )
        ]

    def _project_contact_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        contact_id = data["contact_id"]
        changed_fields = data.get("changed_fields")
        if not changed_fields:
            return []
        rows: list[FieldHistoryEntry] = []
        for field_name, change in changed_fields.items():
            if not isinstance(change, (list, tuple)) or len(change) != 2:
                continue
            entity_type, entity_id, resolved_field = _resolve_contact_field(
                field_name, contact_id
            )
            rows.append(
                self._row(
                    event,
                    data,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field_name=resolved_field,
                    old_value=change[0],
                    new_value=change[1],
                )
            )
        return rows

    def _project_contact_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return [
            self._row(
                event,
                data,
                entity_type=_CONTACT_ENTITY_TYPE,
                entity_id=data["contact_id"],
                field_name="status",
                old_value="active",
                new_value="deleted",
            )
        ]

    def _sub_entity_created(
        self, event: OutboxEvent, data: dict[str, Any], *, entity_type: str, id_key: str
    ) -> list[FieldHistoryEntry]:
        # ITER12-003 Phase 2: per-item add events emitted during a *bulk* contact
        # re-save carry affects_history=False (the aggregate ContactUpdated row is
        # the feed); the projection skips them so the feed stays identical to the
        # dual-write. A missing key means True (create/standalone paths).
        if data.get("affects_history", True) is False:
            return []
        return [
            self._row(
                event,
                data,
                entity_type=entity_type,
                entity_id=data[id_key],
                field_name="status",
                old_value=None,
                new_value="created",
            )
        ]

    def _sub_entity_deleted(
        self, event: OutboxEvent, data: dict[str, Any], *, entity_type: str, id_key: str
    ) -> list[FieldHistoryEntry]:
        return [
            self._row(
                event,
                data,
                entity_type=entity_type,
                entity_id=data[id_key],
                field_name="status",
                old_value="active",
                new_value="deleted",
            )
        ]

    def _project_contact_method_added(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._sub_entity_created(
            event, data, entity_type=_CONTACT_METHOD_ENTITY_TYPE, id_key="method_id"
        )

    def _project_contact_method_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._sub_entity_deleted(
            event, data, entity_type=_CONTACT_METHOD_ENTITY_TYPE, id_key="method_id"
        )

    def _project_contact_address_added(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._sub_entity_created(
            event, data, entity_type=_CONTACT_ADDRESS_ENTITY_TYPE, id_key="address_id"
        )

    def _project_contact_address_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._sub_entity_deleted(
            event, data, entity_type=_CONTACT_ADDRESS_ENTITY_TYPE, id_key="address_id"
        )

    def _project_contact_note_added(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._sub_entity_created(
            event, data, entity_type=_CONTACT_NOTE_ENTITY_TYPE, id_key="note_id"
        )

    def _project_important_date_added(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._sub_entity_created(
            event,
            data,
            entity_type=_CONTACT_IMPORTANT_DATE_ENTITY_TYPE,
            id_key="date_id",
        )

    def _project_important_date_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._sub_entity_deleted(
            event,
            data,
            entity_type=_CONTACT_IMPORTANT_DATE_ENTITY_TYPE,
            id_key="date_id",
        )

    def _project_tag_assigned(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        # ITER12-003 Phase 2: a bulk re-save assigns tags with affects_history=False
        # so the projection skips the per-tag row (the aggregate ContactUpdated
        # "tags" row is the feed); search still consumes the TagAssigned event.
        if data.get("affects_history", True) is False:
            return []
        return [
            self._row(
                event,
                data,
                entity_type=_CONTACT_ENTITY_TYPE,
                entity_id=data["contact_id"],
                field_name="tags",
                old_value=None,
                new_value=data.get("tag_name"),
            )
        ]

    def _project_tag_removed(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return [
            self._row(
                event,
                data,
                entity_type=_CONTACT_ENTITY_TYPE,
                entity_id=data["contact_id"],
                field_name="tags",
                old_value=data.get("tag_name"),
                new_value=None,
            )
        ]

    def _project_contact_relationship_created(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        relationship_id = data["relationship_id"]
        return [
            self._row(
                event,
                data,
                entity_type=_CONTACT_RELATIONSHIP_ENTITY_TYPE,
                entity_id=relationship_id,
                field_name="status",
                old_value=None,
                new_value="created",
            ),
            self._row(
                event,
                data,
                entity_type=_CONTACT_RELATIONSHIP_ENTITY_TYPE,
                entity_id=relationship_id,
                field_name="relationship_type",
                old_value=None,
                new_value=data.get("relationship_type"),
            ),
        ]

    def _project_contact_relationship_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._rows_from_changed_fields(
            event,
            data,
            entity_type=_CONTACT_RELATIONSHIP_ENTITY_TYPE,
            entity_id=data["relationship_id"],
            changed_fields=data.get("changed_fields"),
        )

    def _project_contact_relationship_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return [
            self._row(
                event,
                data,
                entity_type=_CONTACT_RELATIONSHIP_ENTITY_TYPE,
                entity_id=data["relationship_id"],
                field_name="status",
                old_value="active",
                new_value="deleted",
            )
        ]

    def _project_contact_summary_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._rows_from_changed_fields(
            event,
            data,
            entity_type=_CONTACT_SUMMARY_ENTITY_TYPE,
            entity_id=data["contact_id"],
            changed_fields=data.get("changed_fields"),
        )

    # -- helpers -------------------------------------------------------------

    def _rows_from_changed_fields(
        self,
        event: OutboxEvent,
        data: dict[str, Any],
        *,
        entity_id: int,
        changed_fields: dict[str, Sequence[Any]] | None,
        entity_type: str = _JOURNAL_ENTITY_TYPE,
        field_prefix: str = "",
    ) -> list[FieldHistoryEntry]:
        if not changed_fields:
            return []
        rows: list[FieldHistoryEntry] = []
        for field_name, change in changed_fields.items():
            # Only genuine (old, new) pairs are meaningful field changes. Some
            # internal JournalUpdated events carry non-pair signals purely to
            # trigger other workers (e.g. {"calendar_info": True} for calendar
            # sync); "meaningful changes only" means those produce no history.
            if not isinstance(change, (list, tuple)) or len(change) != 2:
                continue
            old_value, new_value = change[0], change[1]
            rows.append(
                self._row(
                    event,
                    data,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field_name=f"{field_prefix}{field_name}",
                    old_value=old_value,
                    new_value=new_value,
                )
            )
        return rows

    def _row(
        self,
        event: OutboxEvent,
        data: dict[str, Any],
        *,
        entity_id: int,
        field_name: str,
        old_value: Any,
        new_value: Any,
        entity_type: str = _JOURNAL_ENTITY_TYPE,
    ) -> FieldHistoryEntry:
        return FieldHistoryEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            old_value=_stringify(old_value),
            new_value=_stringify(new_value),
            changed_by=data.get("changed_by", "system"),
            source=_parse_provenance(data.get("source")),
            event_id=event.event_id,
            created_at=event.occurred_at,
        )


def _stringify(value: Any) -> str | None:
    return None if value is None else str(value)


def _parse_provenance(source: str | None) -> Provenance:
    if not source:
        return Provenance.SYSTEM
    try:
        return Provenance(source)
    except ValueError:
        return Provenance.SYSTEM


def _resolve_contact_field(field_name: str, contact_id: int) -> tuple[str, int, str]:
    """Resolve a ``ContactUpdated`` changed-field key to its (entity_type, entity_id,
    field) row target. Sub-entity keys (``"method_5_value"``) decode to the
    contact_method/address/note row; plain keys belong to the contact itself."""
    match = _SUBENTITY_FIELD_RE.match(field_name)
    if match is None:
        return _CONTACT_ENTITY_TYPE, contact_id, field_name
    prefix, sub_id, field = match.group(1), int(match.group(2)), match.group(3)
    return _SUBENTITY_PREFIX_ENTITY_TYPE[prefix], sub_id, field


# Dispatch table: event_type -> bound handler method name. Built once at import.
_HANDLERS = {
    "JournalCreated": HistoryService._project_journal_created,
    "JournalUpdated": HistoryService._project_journal_updated,
    "JournalDeleted": HistoryService._project_journal_deleted,
    "JournalTypeAdded": HistoryService._project_journal_type_added,
    "JournalTypeRemoved": HistoryService._project_journal_type_removed,
    "RouteCreated": HistoryService._project_route_created,
    "RouteUpdated": HistoryService._project_route_updated,
    "RouteDeleted": HistoryService._project_route_deleted,
    "GearItemUpdated": HistoryService._project_gear_item_updated,
    # Contact events (ITER12-003 Phase 1). The HistoryProjectionConsumer keeps
    # these OUT of its live subscription this phase, so they only run in tests
    # until Phase 2 switches contacts onto the projection and removes the
    # dual-write.
    "ContactCreated": HistoryService._project_contact_created,
    # Sub-entity field edits also arrive as ContactUpdated (with a per-sub-entity
    # key); _project_contact_updated decodes them to the contact_method/address/note
    # row, so there are no separate Contact*Updated handlers.
    "ContactUpdated": HistoryService._project_contact_updated,
    "ContactDeleted": HistoryService._project_contact_deleted,
    "ContactMethodAdded": HistoryService._project_contact_method_added,
    "ContactMethodDeleted": HistoryService._project_contact_method_deleted,
    "ContactAddressAdded": HistoryService._project_contact_address_added,
    "ContactAddressDeleted": HistoryService._project_contact_address_deleted,
    "ContactNoteAdded": HistoryService._project_contact_note_added,
    "ImportantDateAdded": HistoryService._project_important_date_added,
    "ImportantDateDeleted": HistoryService._project_important_date_deleted,
    "TagAssigned": HistoryService._project_tag_assigned,
    "TagRemoved": HistoryService._project_tag_removed,
    "ContactRelationshipCreated": HistoryService._project_contact_relationship_created,
    "ContactRelationshipUpdated": HistoryService._project_contact_relationship_updated,
    "ContactRelationshipDeleted": HistoryService._project_contact_relationship_deleted,
    "ContactSummaryUpdated": HistoryService._project_contact_summary_updated,
}
