"""Domain events for the contacts domain.

ITER12-003 Phase 1: every contact event that the history projection records carries
``source`` (Provenance) and ``changed_by`` in its ``event_data`` so the consumer can
record provenance, mirroring the journal events enriched in ITER12-002. The
exceptions are ``TagUpdated``/``TagDeleted`` (tag-entity events — a tag rename/delete
is not contact history, so the projection ignores them) and
``ContactSummaryRefreshRequested`` (a trigger that only *requests* regeneration; the
resulting change is recorded by ``ContactSummaryUpdated``) — these carry no
provenance by design.

Sub-entity field edits (method/address/note) stay on the existing ``ContactUpdated``
event — a core contact event downstream consumers and search rely on — carrying a
per-sub-entity ``changed_fields`` key shaped ``"{prefix}_{id}_{field}"`` (e.g.
``"method_5_value"``). ``HistoryService._project_contact_updated`` decodes that key
back to the correct ``(entity_type, entity_id)`` row, reproducing the synchronous
dual-write without introducing new event types.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class DomainEvent:
    """Base domain event with transaction support."""

    event_id: str
    occurred_at: datetime
    aggregate_id: int
    event_type: str
    event_data: dict[str, Any]
    transaction: AsyncConnection | None = None


@dataclass(frozen=True)
class ContactCreated(DomainEvent):
    """Event raised when a contact is created."""

    def __init__(
        self,
        contact_id: int,
        first_name: str,
        last_name: str | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_created_{contact_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactCreated",
            event_data={
                "contact_id": contact_id,
                "first_name": first_name,
                "last_name": last_name,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactUpdated(DomainEvent):
    """Event raised when a contact is updated."""

    def __init__(
        self,
        contact_id: int,
        changed_fields: dict[str, Any],
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_updated_{contact_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactUpdated",
            event_data={
                "contact_id": contact_id,
                "changed_fields": changed_fields,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactDeleted(DomainEvent):
    """Event raised when a contact is deleted."""

    def __init__(
        self,
        contact_id: int,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_deleted_{contact_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactDeleted",
            event_data={
                "contact_id": contact_id,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TagAssigned(DomainEvent):
    """Event raised when a tag is assigned to a contact."""

    def __init__(
        self,
        contact_id: int,
        tag_id: int,
        tag_name: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        affects_history: bool = True,
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"tag_assigned_{contact_id}_{tag_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="TagAssigned",
            event_data={
                "contact_id": contact_id,
                "tag_id": tag_id,
                "tag_name": tag_name,
                "source": source.value,
                "changed_by": changed_by,
                # False when emitted during a bulk contact re-save: the aggregate
                # ContactUpdated row is the feed, so the projection skips this
                # per-item marker (search still consumes the event). ITER12-003 P2.
                "affects_history": affects_history,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TagRemoved(DomainEvent):
    """Event raised when a tag is removed from a contact."""

    def __init__(
        self,
        contact_id: int,
        tag_id: int,
        tag_name: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"tag_removed_{contact_id}_{tag_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=contact_id,
            event_type="TagRemoved",
            event_data={
                "contact_id": contact_id,
                "tag_id": tag_id,
                "tag_name": tag_name,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TagUpdated(DomainEvent):
    """Event raised when a tag is updated."""

    def __init__(
        self,
        tag_id: int,
        tag_name: str,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"tag_updated_{tag_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=tag_id,  # Use tag_id as aggregate_id since Tag is the root here
            event_type="TagUpdated",
            event_data={
                "tag_id": tag_id,
                "tag_name": tag_name,
                "changed_fields": changed_fields,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TagDeleted(DomainEvent):
    """Event raised when a tag is deleted."""

    def __init__(
        self,
        tag_id: int,
        tag_name: str,
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"tag_deleted_{tag_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=tag_id,
            event_type="TagDeleted",
            event_data={
                "tag_id": tag_id,
                "tag_name": tag_name,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactMethodAdded(DomainEvent):
    """Event raised when a contact method is added."""

    def __init__(
        self,
        contact_id: int,
        method_id: int,
        method_type: str,
        value: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        affects_history: bool = True,
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_method_added_{contact_id}_{method_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactMethodAdded",
            event_data={
                "contact_id": contact_id,
                "method_id": method_id,
                "method_type": method_type,
                "value": value,
                "source": source.value,
                "changed_by": changed_by,
                # False during a bulk contact re-save (see TagAssigned). ITER12-003 P2.
                "affects_history": affects_history,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactAddressAdded(DomainEvent):
    """Event raised when a contact address is added."""

    def __init__(
        self,
        contact_id: int,
        address_id: int,
        street_line_1: str,
        country_code: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        affects_history: bool = True,
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_address_added_{contact_id}_{address_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactAddressAdded",
            event_data={
                "contact_id": contact_id,
                "address_id": address_id,
                "street_line_1": street_line_1,
                "country_code": country_code,
                "source": source.value,
                "changed_by": changed_by,
                # False during a bulk contact re-save (see TagAssigned). ITER12-003 P2.
                "affects_history": affects_history,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactMethodDeleted(DomainEvent):
    """Event raised when a contact method is deleted."""

    def __init__(
        self,
        contact_id: int,
        method_id: int,
        method_type: str,
        value: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_method_deleted_{contact_id}_{method_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactMethodDeleted",
            event_data={
                "contact_id": contact_id,
                "method_id": method_id,
                "method_type": method_type,
                "value": value,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactAddressDeleted(DomainEvent):
    """Event raised when a contact address is deleted."""

    def __init__(
        self,
        contact_id: int,
        address_id: int,
        street_line_1: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_address_deleted_{contact_id}_{address_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactAddressDeleted",
            event_data={
                "contact_id": contact_id,
                "address_id": address_id,
                "street_line_1": street_line_1,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactNoteAdded(DomainEvent):
    """Event raised when a contact note is added."""

    def __init__(
        self,
        contact_id: int,
        note_id: int,
        content: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        affects_history: bool = True,
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_note_added_{contact_id}_{note_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactNoteAdded",
            event_data={
                "contact_id": contact_id,
                "note_id": note_id,
                "content": (
                    content[:100] + "..." if len(content) > 100 else content
                ),  # Truncate for event
                "source": source.value,
                "changed_by": changed_by,
                # False during a bulk contact re-save (see TagAssigned). ITER12-003 P2.
                "affects_history": affects_history,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ImportantDateAdded(DomainEvent):
    """Event raised when an important date is added to a contact."""

    def __init__(
        self,
        contact_id: int,
        date_id: int,
        date_type: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        affects_history: bool = True,
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_important_date_added_{contact_id}_{date_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ImportantDateAdded",
            event_data={
                "contact_id": contact_id,
                "date_id": date_id,
                "date_type": date_type,
                "source": source.value,
                "changed_by": changed_by,
                # False during a bulk contact re-save (see TagAssigned). ITER12-003 P2.
                "affects_history": affects_history,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ImportantDateDeleted(DomainEvent):
    """Event raised when an important date is deleted from a contact."""

    def __init__(
        self,
        contact_id: int,
        date_id: int,
        date_type: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_important_date_deleted_{contact_id}_{date_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ImportantDateDeleted",
            event_data={
                "contact_id": contact_id,
                "date_id": date_id,
                "date_type": date_type,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactRelationshipCreated(DomainEvent):
    """Event raised when a contact relationship is created."""

    def __init__(
        self,
        relationship_id: int,
        from_contact_id: int,
        to_contact_id: int | None,
        relationship_type: str,
        to_user: bool,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_relationship_created_{relationship_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=from_contact_id,
            event_type="ContactRelationshipCreated",
            event_data={
                "relationship_id": relationship_id,
                "from_contact_id": from_contact_id,
                "to_contact_id": to_contact_id,
                "relationship_type": relationship_type,
                "to_user": to_user,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactRelationshipUpdated(DomainEvent):
    """Event raised when a contact relationship is updated."""

    def __init__(
        self,
        relationship_id: int,
        from_contact_id: int,
        to_contact_id: int | None,
        relationship_type: str,
        to_user: bool,
        changed_fields: dict[str, Any] | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_relationship_updated_{relationship_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=from_contact_id,
            event_type="ContactRelationshipUpdated",
            event_data={
                "relationship_id": relationship_id,
                "from_contact_id": from_contact_id,
                "to_contact_id": to_contact_id,
                "relationship_type": relationship_type,
                "to_user": to_user,
                "changed_fields": changed_fields or {},
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactRelationshipDeleted(DomainEvent):
    """Event raised when a contact relationship is deleted."""

    def __init__(
        self,
        relationship_id: int,
        from_contact_id: int,
        to_contact_id: int | None,
        relationship_type: str,
        to_user: bool,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_relationship_deleted_{relationship_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=from_contact_id,
            event_type="ContactRelationshipDeleted",
            event_data={
                "relationship_id": relationship_id,
                "from_contact_id": from_contact_id,
                "to_contact_id": to_contact_id,
                "relationship_type": relationship_type,
                "to_user": to_user,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactSummaryRefreshRequested(DomainEvent):
    """Event raised when a contact summary regeneration is requested.

    Buffered intent: the summary consumer records it as a rolling-debounce
    marker (and the search indexer reindexes the contact); actual generation
    is driven by ``ContactSummaryRefreshDue`` once the quiet period elapses.
    """

    def __init__(
        self,
        contact_id: int,
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_summary_refresh_{contact_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactSummaryRefreshRequested",
            event_data={"contact_id": contact_id},
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactSummaryRefreshDue(DomainEvent):
    """Event raised when a buffered summary refresh becomes due.

    ``ContactSummaryRefreshRequested`` is buffered intent: the summary consumer
    records it as a debounce marker instead of generating immediately. This
    event is the generate-now command, published by the summary refresh sweeper
    once the contact has been quiet for the buffer window (or directly by the
    manual refresh endpoint, which bypasses the buffer).
    """

    def __init__(
        self,
        contact_id: int,
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_summary_refresh_due_{contact_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactSummaryRefreshDue",
            event_data={"contact_id": contact_id},
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactSummaryUpdated(DomainEvent):
    """Event raised when a contact summary actually changes.

    The existing ``ContactSummaryRefreshRequested`` only *triggers* regeneration;
    this event records the *result* (summary text / disabled flag changing) so the
    history projection can write the ``contact_summary`` rows the dual-write writes.
    Defaults to ``Provenance.SUMMARY_REGENERATION`` since summaries are AI-generated.
    """

    def __init__(
        self,
        contact_id: int,
        changed_fields: dict[str, Any],
        source: Provenance = Provenance.SUMMARY_REGENERATION,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        super().__init__(
            event_id=f"contact_summary_updated_{contact_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=contact_id,
            event_type="ContactSummaryUpdated",
            event_data={
                "contact_id": contact_id,
                "changed_fields": changed_fields,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class ContactMerged(DomainEvent):
    """Event raised when a source contact is merged into a surviving contact.

    Carries both contact IDs and provenance so downstream consumers (external-sync
    reconciliation) can reconcile the survivor's external links and remote records.
    ``external_collisions`` lists the same-service links that could not simply
    carry over — the survivor already had a link for that service, so the source's
    local row was removed during the merge and its remote ``external_entity_id`` is
    surfaced here for the integration workers to reconcile remotely. No worker
    consumer exists yet; an absent consumer must not error. The aggregate is the
    survivor, whose identity is preserved by the merge.
    """

    def __init__(
        self,
        survivor_contact_id: int,
        source_contact_id: int,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
        external_collisions: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            event_id=f"contact_merged_{survivor_contact_id}_{source_contact_id}_{datetime.now(tz=UTC).isoformat()}",
            occurred_at=datetime.now(tz=UTC),
            aggregate_id=survivor_contact_id,
            event_type="ContactMerged",
            event_data={
                "survivor_contact_id": survivor_contact_id,
                "source_contact_id": source_contact_id,
                "source": source.value,
                "changed_by": changed_by,
                "external_collisions": external_collisions or [],
            },
            transaction=transaction,
        )
