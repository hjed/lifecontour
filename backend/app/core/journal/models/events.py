"""Domain events for the journal domain."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

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
class JournalCreated(DomainEvent):
    """Event raised when a journal is created."""

    def __init__(
        self,
        journal_id: int,
        user_id: str,
        title: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_created_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalCreated",
            event_data={
                "journal_id": journal_id,
                "user_id": user_id,
                "title": title,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalUpdated(DomainEvent):
    """Event raised when a journal is updated."""

    def __init__(
        self,
        journal_id: int,
        changed_fields: dict[str, Any],
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_updated_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalUpdated",
            event_data={
                "journal_id": journal_id,
                "changed_fields": changed_fields,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalDeleted(DomainEvent):
    """Event raised when a journal is deleted."""

    def __init__(
        self,
        journal_id: int,
        user_id: str,
        external_identifiers: dict[str, list[dict[str, Any]]] | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_deleted_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalDeleted",
            event_data={
                "journal_id": journal_id,
                "user_id": user_id,
                "external_identifiers": external_identifiers or {},
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTypeAdded(DomainEvent):
    """Event raised when a type is added to a journal."""

    def __init__(
        self,
        journal_id: int,
        journal_type: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_type_added_{journal_id}_{journal_type}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTypeAdded",
            event_data={
                "journal_id": journal_id,
                "journal_type": journal_type,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTypeRemoved(DomainEvent):
    """Event raised when a type is removed from a journal."""

    def __init__(
        self,
        journal_id: int,
        journal_type: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_type_removed_{journal_id}_{journal_type}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTypeRemoved",
            event_data={
                "journal_id": journal_id,
                "journal_type": journal_type,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTagAssigned(DomainEvent):
    """Event raised when a tag is assigned to a journal.

    Journal-prefixed because the contact domain already publishes ``TagAssigned``
    for its own namespace, and the history projection dispatches on the event-type
    string alone. Carries ``tag_name`` so the projection needs no join, and
    stringifies ``tag_id`` because the payload round-trips through JSON.
    """

    def __init__(
        self,
        journal_id: int,
        tag_id: UUID,
        tag_name: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_tag_assigned_{journal_id}_{tag_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTagAssigned",
            event_data={
                "journal_id": journal_id,
                "tag_id": str(tag_id),
                "tag_name": tag_name,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTagRemoved(DomainEvent):
    """Event raised when a tag is removed from a journal."""

    def __init__(
        self,
        journal_id: int,
        tag_id: UUID,
        tag_name: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_tag_removed_{journal_id}_{tag_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTagRemoved",
            event_data={
                "journal_id": journal_id,
                "tag_id": str(tag_id),
                "tag_name": tag_name,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTagDeleted(DomainEvent):
    """Event raised when a tag a journal carried was deleted outright.

    Published once per journal that carried the tag, for the same reason
    :class:`JournalTagRenamed` is: the journal is the aggregate whose activity
    feed the entry lands in, and a tag-scoped event would have no integer
    ``aggregate_id`` to use.

    The payload matches :class:`JournalTagRemoved` deliberately. Deleting a tag
    un-assigns it from every journal, so from a journal's point of view the two
    are the same change and the feed should not ask the user to care which
    tag-namespace operation caused it.
    """

    def __init__(
        self,
        journal_id: int,
        tag_id: UUID,
        tag_name: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_tag_deleted_{journal_id}_{tag_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTagDeleted",
            event_data={
                "journal_id": journal_id,
                "tag_id": str(tag_id),
                "tag_name": tag_name,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTagMerged(DomainEvent):
    """Event raised when a tag a journal carried was merged into another.

    Published once per journal that carried the **source** tag, matching the
    other tag fan-out events. On most journals the merge swaps the source for the
    target; on a journal that already carried the target nothing arrives and only
    the source leaves. ``already_had_target`` records which of the two happened,
    so the projection can describe it without querying the assignment table after
    the fact — by then the merge has already re-pointed the rows.

    The ``event_id`` names **both** tags: two different sources folded into one
    target on the same journal would otherwise collide under the history dedup
    index, and the second merge's row would be silently dropped.
    """

    def __init__(
        self,
        journal_id: int,
        source_tag_id: UUID,
        target_tag_id: UUID,
        source_tag_name: str,
        target_tag_name: str,
        already_had_target: bool,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=(
                f"journal_tag_merged_{journal_id}_{source_tag_id}_"
                f"{target_tag_id}_{now.isoformat()}"
            ),
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTagMerged",
            event_data={
                "journal_id": journal_id,
                "source_tag_id": str(source_tag_id),
                "target_tag_id": str(target_tag_id),
                "source_tag_name": source_tag_name,
                "target_tag_name": target_tag_name,
                "already_had_target": already_had_target,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTagRenamed(DomainEvent):
    """Event raised when a tag carried by a journal is renamed.

    Published once per journal that carries the tag rather than once per tag:
    the journal is the aggregate whose activity feed the entry lands in, and a
    tag-scoped event would have no integer ``aggregate_id`` to use — journal
    tags are UUID-keyed. Carries both names so the projection can write a real
    field change without a join, the same way the assignment events carry
    ``tag_name``.

    Only a *name* change publishes this. A tag's colour, description and parent
    are invisible on a journal, so changing them alters nothing about it and
    must not produce history.
    """

    def __init__(
        self,
        journal_id: int,
        tag_id: UUID,
        old_name: str,
        new_name: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"journal_tag_renamed_{journal_id}_{tag_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTagRenamed",
            event_data={
                "journal_id": journal_id,
                "tag_id": str(tag_id),
                "old_name": old_name,
                "new_name": new_name,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class RouteCreated(DomainEvent):
    """Event raised when a route is created."""

    def __init__(
        self,
        route_id: str,
        journal_id: int,
        name: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        # Use UUID.int for deterministic aggregate_id (DomainEvent expects int)
        # This is stable across process restarts unlike hash()
        aggregate_id = UUID(route_id).int % (10**9)
        super().__init__(
            event_id=f"route_created_{route_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=aggregate_id,
            event_type="RouteCreated",
            event_data={
                "route_id": route_id,
                "journal_id": journal_id,
                "name": name,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class RouteUpdated(DomainEvent):
    """Event raised when a route is updated."""

    def __init__(
        self,
        route_id: str,
        journal_id: int,
        changed_fields: dict[str, Any],
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        # Use UUID.int for deterministic aggregate_id (DomainEvent expects int)
        aggregate_id = UUID(route_id).int % (10**9)
        super().__init__(
            event_id=f"route_updated_{route_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=aggregate_id,
            event_type="RouteUpdated",
            event_data={
                "route_id": route_id,
                "journal_id": journal_id,
                "changed_fields": changed_fields,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class RouteDeleted(DomainEvent):
    """Event raised when a route is deleted."""

    def __init__(
        self,
        route_id: str,
        journal_id: int,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        # Use UUID.int for deterministic aggregate_id (DomainEvent expects int)
        aggregate_id = UUID(route_id).int % (10**9)
        super().__init__(
            event_id=f"route_deleted_{route_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=aggregate_id,
            event_type="RouteDeleted",
            event_data={
                "route_id": route_id,
                "journal_id": journal_id,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class GearItemUpdated(DomainEvent):
    """Event raised when a gear item is updated.

    ``journal_id`` is optional: gear items are shared across journals
    (many-to-many), so a plain gear edit has no single parent journal. Only the
    journal-scoped gear-usage edit path populates it; the history projection
    skips gear events that carry no ``journal_id``.
    """

    def __init__(
        self,
        gear_item_id: str,
        changed_fields: dict[str, Any],
        journal_id: int | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        # Use UUID.int for deterministic aggregate_id (DomainEvent expects int)
        aggregate_id = UUID(gear_item_id).int % (10**9)
        super().__init__(
            event_id=f"gear_item_updated_{gear_item_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=aggregate_id,
            event_type="GearItemUpdated",
            event_data={
                "gear_item_id": gear_item_id,
                "journal_id": journal_id,
                "changed_fields": changed_fields,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )
