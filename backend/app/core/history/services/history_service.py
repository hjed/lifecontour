"""Projection of journal domain events into field history rows.

``HistoryService.project_event`` is a *pure* mapping from a single journal/route/
gear domain event (delivered as an :class:`OutboxEvent`) to the list of
:class:`FieldHistoryEntry` rows that should be written for it. It performs no I/O,
so it is trivially unit-testable; the :class:`HistoryProjectionConsumer` owns the
repository and the idempotent writes.

Design (ITER12-002 Phase 1):

* Every change is tagged to the *journal* aggregate (``entity_type="journal"``,
  ``entity_id=journal_id``). Route and gear ids are UUIDs, but ``field_history``
  keys on an integer ``entity_id``; grouping route/gear changes under the journal
  (with the route/gear context encoded in ``field_name``) keeps them on the
  integer key, survives route deletion, and needs no join to read back.
* Provenance (``source`` + ``changed_by``) and the originating ``event_id`` travel
  in ``event_data`` and are copied onto every row. ``created_at`` is set to
  ``event.occurred_at`` so history reflects when the change happened, not when it
  was projected.
* ``changed_fields`` values arrive as ``[old, new]`` lists after the JSON round
  trip through Redis, so we index positionally rather than unpacking a tuple.
"""

from collections.abc import Sequence
from typing import Any

from core_shared.models.history import Provenance

from app.core.history.models import FieldHistoryEntry
from app.infrastructure.events.outbox_repository import OutboxEvent

_JOURNAL_ENTITY_TYPE = "journal"


class HistoryService:
    """Maps journal domain events to field-history rows."""

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
        return [
            self._row(
                event,
                data,
                entity_id=data["journal_id"],
                field_name=f"route:{route_id}:__created__",
                old_value=None,
                new_value=data.get("name"),
            )
        ]

    def _project_route_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        route_id = data["route_id"]
        return self._rows_from_changed_fields(
            event,
            data,
            entity_id=data["journal_id"],
            changed_fields=data.get("changed_fields"),
            field_prefix=f"route:{route_id}:",
        )

    def _project_route_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        route_id = data["route_id"]
        return [
            self._row(
                event,
                data,
                entity_id=data["journal_id"],
                field_name=f"route:{route_id}:__deleted__",
                old_value=None,
                new_value=None,
            )
        ]

    def _project_gear_item_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        journal_id = data.get("journal_id")
        # Gear is shared across journals; a gear edit with no journal context is
        # not attributable to a single journal's history, so it is skipped.
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

    # -- helpers -------------------------------------------------------------

    def _rows_from_changed_fields(
        self,
        event: OutboxEvent,
        data: dict[str, Any],
        *,
        entity_id: int,
        changed_fields: dict[str, Sequence[Any]] | None,
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
    ) -> FieldHistoryEntry:
        return FieldHistoryEntry(
            entity_type=_JOURNAL_ENTITY_TYPE,
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
}
