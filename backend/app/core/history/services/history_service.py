"""Projection of journal, contact and task domain events into field history rows.

``HistoryService.project_event`` is a *pure* mapping from a single journal/route/
gear, contact or task domain event (delivered as an :class:`OutboxEvent`) to the
list of :class:`FieldHistoryEntry` rows that should be written for it. It performs
no I/O, so it is trivially unit-testable; the :class:`HistoryProjectionConsumer`
owns the repository and the idempotent writes.

Tasks: a task is a top-level aggregate keyed by its own
integer id, so its rows go under ``("task", task_id)`` and use the *journal*
marker convention (``__created__``/``__deleted__``) rather than the contact one
(``field_name="status"``). The contact shape exists because contact history
spreads across a family of sub-entity rows; a task has none. Every type the
domain publishes is mapped: the three lifecycle types, the due-anchor move, and
the intermediate-journal pair. Nothing a task write announces is written to the
stream and then never read.

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
from app.core.tasks.models.events import contact_field_name, journal_field_name
from app.infrastructure.events.outbox_repository import OutboxEvent

_JOURNAL_ENTITY_TYPE = "journal"

# The task aggregate. ``tasks.id`` is an ``Integer``, so task rows sit in the
# shared ``field_history.entity_id`` column with no migration — unlike routes and
# gear, whose UUID ids are why those events are filed under their journal.
_TASK_ENTITY_TYPE = "task"

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

    def _project_journal_tag_assigned(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._journal_tag_rows(
            event, data, old_value=None, new_value=data.get("tag_name")
        )

    def _project_journal_tag_removed(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        return self._journal_tag_rows(
            event, data, old_value=data.get("tag_name"), new_value=None
        )

    def _project_journal_tag_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """The tag was destroyed, which reads on each journal as a removal.

        Deliberately the same row shape as ``JournalTagRemoved``: deleting a tag
        un-assigns it everywhere, so from the journal's point of view the two are
        the same change and the feed should not ask the user to distinguish the
        tag-namespace operation that caused it.
        """
        return self._journal_tag_rows(
            event, data, old_value=data.get("tag_name"), new_value=None
        )

    def _project_journal_tag_merged(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """The tag was folded into another, which reads two ways per journal.

        A journal that carried only the source swapped one tag for another, so
        both names go on the row and ``ActivityItem`` renders it as a change. A
        journal that already carried the target gained nothing — only the source
        left it — so recording the swap there would claim a change that did not
        occur.

        Only the swap branch guards its names here. The removal branch needs no
        guard of its own: with ``new_value=None`` the shared helper's "names
        nothing" check already covers a missing ``source_tag_name``. The swap
        branch is not covered by it, for the reason
        ``_project_journal_tag_renamed`` explains — a swap missing its target name
        would pass that check as ``(source, None)`` and render as a removal that
        never happened. An absent flag is read as neither branch rather than
        defaulting to the swap on truthiness.
        """
        source_name = data.get("source_tag_name")
        already_had_target = data.get("already_had_target")

        if already_had_target is True:
            return self._journal_tag_rows(
                event, data, old_value=source_name, new_value=None
            )

        if already_had_target is not False:
            return []

        target_name = data.get("target_tag_name")
        if source_name is None or target_name is None:
            return []
        return self._journal_tag_rows(
            event, data, old_value=source_name, new_value=target_name
        )

    def _project_journal_tag_renamed(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """The tag a journal carries changed label — a field change, not a swap.

        Both names present is what makes the shared ``ActivityItem`` render
        "Changed Tags from ... to ..." rather than an add or a remove, so half a
        rename is checked for here: the shared helper's "nothing to name" guard
        would let ``("Hiking", None)`` through as a removal that never happened.
        """
        old_name = data.get("old_name")
        new_name = data.get("new_name")
        if old_name is None or new_name is None:
            return []
        return self._journal_tag_rows(
            event, data, old_value=old_name, new_value=new_name
        )

    def _journal_tag_rows(
        self,
        event: OutboxEvent,
        data: dict[str, Any],
        *,
        old_value: str | None,
        new_value: str | None,
    ) -> list[FieldHistoryEntry]:
        """One ``tags`` row on the journal, naming the tag the change concerns.

        A payload that names no tag at all projects nothing rather than raising:
        the row would render as "Changed Tags from null to null", and a raising
        handler would dead-letter the whole batch and stall history for every
        event behind it. No current producer omits the name.
        """
        if old_value is None and new_value is None:
            return []
        return [
            self._row(
                event,
                data,
                entity_id=data["journal_id"],
                field_name="tags",
                old_value=old_value,
                new_value=new_value,
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

    # -- task handlers ------------------------------------------------------

    def _project_task_created(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """The marker that opens a task's history, plus the people it named.

        The marker carries the task's text, as the journal's carries its title,
        so the first line of a task's history says what the task is.

        **It does not itemise the rest of the payload.** A later status move and
        a later retarget each publish a self-describing ``(old, new)`` pair, so
        neither needs an opening value to read correctly. A contact *unlink*
        does — it publishes ``(id, None)`` — so a create that named people has to
        announce them, or a task created with Sarah and later unlinked from her
        shows a removal with no addition before it. That asymmetry is why the
        event carries ``contact_ids`` at all, and fanning the list out here is
        the half that finishes it: ``contact_ids`` is a list rather than an
        ``(old, new)`` pair, so ``_rows_from_changed_fields`` cannot do it.

        The keys come from ``contact_field_name`` — the same function
        ``TaskService`` builds them with — because a format that lives in two
        places is one that can drift, and these rows have to sort alongside the
        ones a later link publishes.
        """
        task_id = data["task_id"]
        rows = [
            self._row(
                event,
                data,
                entity_type=_TASK_ENTITY_TYPE,
                entity_id=task_id,
                field_name="__created__",
                old_value=None,
                new_value=data.get("text"),
            )
        ]
        # ``or []`` rather than a required key: the history-projection group
        # reads the stream from id 0, so it can be handed a TaskCreated from
        # before contact_ids joined the payload. Raising would dead-letter the
        # batch and stall history for every event queued behind it, to record a
        # task that had no contacts anyway.
        for contact_id in data.get("contact_ids") or []:
            rows.append(
                self._row(
                    event,
                    data,
                    entity_type=_TASK_ENTITY_TYPE,
                    entity_id=task_id,
                    field_name=contact_field_name(contact_id),
                    old_value=None,
                    new_value=contact_id,
                )
            )
        return rows

    def _project_task_updated(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """One row per changed field: the text, the status, and each contact.

        Three kinds of change reach this one event type, and none needs a branch
        here. ``_rows_from_changed_fields`` reads ``change[0]`` as the old value
        and never looks at the key, so a ``contact:{id}`` key linking somebody
        (``(None, id)``) or unlinking them (``(id, None)``) projects like any
        other field — one row, naming the person, the right way round.

        **``TaskDueJournalRetargeted`` is mapped here too**, which is why this
        docstring is not only about updates. That event carries a
        ``changed_fields`` payload *for this reason*: ``due_journal_id: (old,
        new)`` and, only when the deferral reopened the task, ``status: (old,
        "not_done")``, so the anchor move and the reopen each read as their own
        line with no handler of its own. The retarget's retained intermediate
        link is not in that payload either — it is a :class:`TaskJournalLinked`
        of its own — so nothing is left for a second handler to do, and writing
        one would be two places for "how a task field change becomes a row" to
        disagree.
        """
        return self._rows_from_changed_fields(
            event,
            data,
            entity_type=_TASK_ENTITY_TYPE,
            entity_id=data["task_id"],
            changed_fields=data.get("changed_fields"),
        )

    def _project_task_journal_linked(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """A journal joined the task's intermediate links."""
        return self._task_journal_link_rows(event, data, linked=True)

    def _project_task_journal_unlinked(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """A journal left them."""
        return self._task_journal_link_rows(event, data, linked=False)

    def _task_journal_link_rows(
        self, event: OutboxEvent, data: dict[str, Any], *, linked: bool
    ) -> list[FieldHistoryEntry]:
        """One row naming the journal, in the direction the event announces.

        ``old=None, new=<journal>`` for a link and the reverse for an unlink —
        the ``JournalTagAssigned``/``JournalTagRemoved`` shape that
        :class:`TaskJournalLinked`'s own docstring names as its model, and the
        one ``contact:{id}`` keys already produce for a task's people. Direction
        is positional and nothing else on the row carries it, so an unlink
        projected the wrong way round reads in the feed as the journal being
        added with nothing to contradict it.

        A payload naming no journal projects nothing rather than raising. The row
        would read as "linked journal None", and a raising handler dead-letters
        the whole batch and stalls history for every event queued behind it —
        the same trade ``_journal_tag_rows`` makes.

        **``origin`` is not projected**, and :func:`journal_field_name` records
        why: the link and the unlink that removes it have to share a field name
        to read as a pair, and an unlink has no origin to spell.
        """
        journal_id = data.get("journal_id")
        if journal_id is None:
            return []
        return [
            self._row(
                event,
                data,
                entity_type=_TASK_ENTITY_TYPE,
                entity_id=data["task_id"],
                field_name=journal_field_name(journal_id),
                old_value=None if linked else journal_id,
                new_value=journal_id if linked else None,
            )
        ]

    def _project_task_deleted(
        self, event: OutboxEvent, data: dict[str, Any]
    ) -> list[FieldHistoryEntry]:
        """A marker, because the event is one.

        ``TaskService.delete_task`` reads nothing before deleting, so the event
        carries no text and no anchors and there is no value to record on either
        side — the same reason ``JournalDeleted`` projects a bare marker.

        Everything the row needs comes off the payload. Tasks are hard-deleted,
        so this row can never be joined back to a ``tasks`` row, which is why the
        event carries ``user_id`` and why a task-scoped read can still find it.
        """
        return [
            self._row(
                event,
                data,
                entity_type=_TASK_ENTITY_TYPE,
                entity_id=data["task_id"],
                field_name="__deleted__",
                old_value=None,
                new_value=None,
            )
        ]

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
    "JournalTagAssigned": HistoryService._project_journal_tag_assigned,
    "JournalTagRemoved": HistoryService._project_journal_tag_removed,
    "JournalTagRenamed": HistoryService._project_journal_tag_renamed,
    "JournalTagDeleted": HistoryService._project_journal_tag_deleted,
    "JournalTagMerged": HistoryService._project_journal_tag_merged,
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
    # Task events. The consumer subscribes to exactly the types listed here, so
    # an entry added without the subscription writes history nobody reads, and a
    # subscription added without an entry consumes an event and drops it
    # silently. Both halves move together, asserted in both directions by
    # test_history_projection_consumer.py.
    #
    # Every type the tasks domain publishes is mapped — and the retarget shares
    # TaskUpdated's handler rather than having one of its own, because it carries
    # the same changed_fields payload. See that method.
    "TaskCreated": HistoryService._project_task_created,
    "TaskUpdated": HistoryService._project_task_updated,
    "TaskDueJournalRetargeted": HistoryService._project_task_updated,
    "TaskJournalLinked": HistoryService._project_task_journal_linked,
    "TaskJournalUnlinked": HistoryService._project_task_journal_unlinked,
    "TaskDeleted": HistoryService._project_task_deleted,
}
