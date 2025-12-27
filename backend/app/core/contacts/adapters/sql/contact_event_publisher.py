"""SQL implementation of ContactEventPublisher that stores events in contact_edit_event table."""

import json
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    DomainEventProtocol,
)


class SqlContactEventPublisher(ContactEventPublisher):
    """SQL implementation that stores events in the contact_edit_event table."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def publish(self, event: DomainEventProtocol) -> None:
        """Publish a domain event by storing it in the contact_edit_event table."""
        # Store event in dedicated events table
        query = text(
            """
            INSERT INTO contact_edit_event
            (event_id, event_type, aggregate_id, event_data, occurred_at, correlation_id)
            VALUES (:event_id, :event_type, :aggregate_id, :event_data, :occurred_at, :correlation_id)
        """
        )

        await self.conn.execute(
            query,
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "event_data": json.dumps(event.event_data),
                "occurred_at": event.occurred_at,
                "correlation_id": getattr(event, "correlation_id", None),
            },
        )

    async def publish_batch(self, events: Sequence[DomainEventProtocol]) -> None:
        """Publish multiple domain events."""
        for event in events:
            await self.publish(event)
