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
