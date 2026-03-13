"""Domain events for the journal domain."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

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
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now()
        super().__init__(
            event_id=f"journal_created_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalCreated",
            event_data={
                "journal_id": journal_id,
                "title": title,
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
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now()
        super().__init__(
            event_id=f"journal_updated_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalUpdated",
            event_data={"journal_id": journal_id, "changed_fields": changed_fields},
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalDeleted(DomainEvent):
    """Event raised when a journal is deleted."""

    def __init__(self, journal_id: int, transaction: AsyncConnection | None = None):
        now = datetime.now()
        super().__init__(
            event_id=f"journal_deleted_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalDeleted",
            event_data={"journal_id": journal_id},
            transaction=transaction,
        )


@dataclass(frozen=True)
class JournalTypeAdded(DomainEvent):
    """Event raised when a type is added to a journal."""

    def __init__(
        self,
        journal_id: int,
        journal_type: str,
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now()
        super().__init__(
            event_id=f"journal_type_added_{journal_id}_{journal_type}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTypeAdded",
            event_data={
                "journal_id": journal_id,
                "journal_type": journal_type,
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
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now()
        super().__init__(
            event_id=f"journal_type_removed_{journal_id}_{journal_type}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=journal_id,
            event_type="JournalTypeRemoved",
            event_data={
                "journal_id": journal_id,
                "journal_type": journal_type,
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
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now()
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
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class RouteUpdated(DomainEvent):
    """Event raised when a route is updated."""

    def __init__(
        self,
        route_id: str,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now()
        # Use UUID.int for deterministic aggregate_id (DomainEvent expects int)
        aggregate_id = UUID(route_id).int % (10**9)
        super().__init__(
            event_id=f"route_updated_{route_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=aggregate_id,
            event_type="RouteUpdated",
            event_data={"route_id": route_id, "changed_fields": changed_fields},
            transaction=transaction,
        )


@dataclass(frozen=True)
class RouteDeleted(DomainEvent):
    """Event raised when a route is deleted."""

    def __init__(self, route_id: str, transaction: AsyncConnection | None = None):
        now = datetime.now()
        # Use UUID.int for deterministic aggregate_id (DomainEvent expects int)
        aggregate_id = UUID(route_id).int % (10**9)
        super().__init__(
            event_id=f"route_deleted_{route_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=aggregate_id,
            event_type="RouteDeleted",
            event_data={"route_id": route_id},
            transaction=transaction,
        )
