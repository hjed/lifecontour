"""Contact domain event service."""

import uuid

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import DomainEvent
from app.core.contacts.models.repositories import (
    ContactEditEvent,
    ContactEditEventRepository,
)


class ContactEventService:
    """Service for managing contact domain events."""

    def __init__(self, event_repo: ContactEditEventRepository):
        self.event_repo = event_repo

    async def record_domain_event(
        self, event: DomainEvent, _transaction: AsyncConnection | None = None
    ) -> None:
        """Record a domain event."""
        edit_event = ContactEditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
            event_data={
                "event_id": event.event_id,
                "occurred_at": (
                    event.occurred_at.isoformat()
                    if hasattr(event.occurred_at, "isoformat")
                    else str(event.occurred_at)
                ),
                "correlation_id": getattr(event, "correlation_id", None),
                **event.event_data,
            },
            occurred_at=(
                event.occurred_at.isoformat()
                if hasattr(event.occurred_at, "isoformat")
                else str(event.occurred_at)
            ),
            correlation_id=getattr(event, "correlation_id", None),
        )
        await self.event_repo.store_event(edit_event)

    async def get_contact_events(
        self,
        contact_id: int,
        limit: int = 50,
        _transaction: AsyncConnection | None = None,
    ) -> list[ContactEditEvent]:
        """Get domain events for a specific contact."""
        return await self.event_repo.get_events_for_contact(contact_id, limit)

    async def get_events_by_type(
        self,
        event_type: str,
        limit: int = 50,
        _transaction: AsyncConnection | None = None,
    ) -> list[ContactEditEvent]:
        """Get events by type."""
        return await self.event_repo.get_events_by_type(event_type, limit)
