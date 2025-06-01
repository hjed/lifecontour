"""Domain events for the contacts domain."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

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

    def __init__(self, contact_id: int, first_name: str, last_name: str | None = None, transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"contact_created_{contact_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="ContactCreated",
            event_data={
                "contact_id": contact_id,
                "first_name": first_name,
                "last_name": last_name
            },
            transaction=transaction
        )


@dataclass(frozen=True)
class ContactUpdated(DomainEvent):
    """Event raised when a contact is updated."""

    def __init__(self, contact_id: int, changed_fields: dict[str, Any], transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"contact_updated_{contact_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="ContactUpdated",
            event_data={
                "contact_id": contact_id,
                "changed_fields": changed_fields
            },
            transaction=transaction
        )


@dataclass(frozen=True)
class ContactDeleted(DomainEvent):
    """Event raised when a contact is deleted."""

    def __init__(self, contact_id: int, transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"contact_deleted_{contact_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="ContactDeleted",
            event_data={
                "contact_id": contact_id
            },
            transaction=transaction
        )


@dataclass(frozen=True)
class TagAssigned(DomainEvent):
    """Event raised when a tag is assigned to a contact."""

    def __init__(self, contact_id: int, tag_id: int, tag_name: str, transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"tag_assigned_{contact_id}_{tag_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="TagAssigned",
            event_data={
                "contact_id": contact_id,
                "tag_id": tag_id,
                "tag_name": tag_name
            },
            transaction=transaction
        )


@dataclass(frozen=True)
class TagRemoved(DomainEvent):
    """Event raised when a tag is removed from a contact."""

    def __init__(self, contact_id: int, tag_id: int, tag_name: str, transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"tag_removed_{contact_id}_{tag_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="TagRemoved",
            event_data={
                "contact_id": contact_id,
                "tag_id": tag_id,
                "tag_name": tag_name
            },
            transaction=transaction
        )


@dataclass(frozen=True)
class ContactMethodAdded(DomainEvent):
    """Event raised when a contact method is added."""

    def __init__(self, contact_id: int, method_id: int, method_type: str, value: str, transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"contact_method_added_{contact_id}_{method_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="ContactMethodAdded",
            event_data={
                "contact_id": contact_id,
                "method_id": method_id,
                "method_type": method_type,
                "value": value
            },
            transaction=transaction
        )


@dataclass(frozen=True)
class ContactAddressAdded(DomainEvent):
    """Event raised when a contact address is added."""

    def __init__(self, contact_id: int, address_id: int, street_line_1: str, country_code: str, transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"contact_address_added_{contact_id}_{address_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="ContactAddressAdded",
            event_data={
                "contact_id": contact_id,
                "address_id": address_id,
                "street_line_1": street_line_1,
                "country_code": country_code
            },
            transaction=transaction
        )


@dataclass(frozen=True)
class ContactNoteAdded(DomainEvent):
    """Event raised when a contact note is added."""

    def __init__(self, contact_id: int, note_id: int, content: str, transaction: AsyncConnection | None = None):
        super().__init__(
            event_id=f"contact_note_added_{contact_id}_{note_id}_{datetime.now().isoformat()}",
            occurred_at=datetime.now(),
            aggregate_id=contact_id,
            event_type="ContactNoteAdded",
            event_data={
                "contact_id": contact_id,
                "note_id": note_id,
                "content": content[:100] + "..." if len(content) > 100 else content  # Truncate for event
            },
            transaction=transaction
        )
