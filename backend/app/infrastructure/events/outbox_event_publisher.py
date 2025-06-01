"""
Outbox event publisher implementation for transactional outbox pattern.

Implements ContactEventPublisher interface to store events in the outbox_events table
within the same transaction as business data changes, ensuring reliable event delivery.
"""

import json

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import DomainEvent
from app.core.contacts.models.repositories import ContactEventPublisher

logger = structlog.get_logger()


class OutboxEventPublisher(ContactEventPublisher):
    """
    Outbox implementation of ContactEventPublisher.

    Stores events in the outbox_events table for reliable event publishing
    via the transactional outbox pattern.
    """

    def __init__(self, connection: AsyncConnection):
        """
        Initialize with database connection.

        Args:
            connection: Async database connection for transaction support
        """
        self.conn = connection

    async def publish(self, event: DomainEvent) -> None:
        """
        Publish a domain event by storing it in the outbox_events table.

        Args:
            event: Domain event to publish
        """
        try:
            query = text(
                """
                INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data, occurred_at, retry_count, created_at)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, :occurred_at, :retry_count, :created_at)
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
                    "retry_count": 0,
                    "created_at": event.occurred_at,
                },
            )

            logger.debug(
                "Event published to outbox",
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
            )

        except Exception as e:
            logger.error(
                "Failed to publish event to outbox",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
            )
            raise

    async def publish_batch(self, events: list[DomainEvent]) -> None:
        """
        Publish multiple domain events in a batch.

        Args:
            events: List of domain events to publish
        """
        if not events:
            return

        try:
            # For now, publish events one by one
            # Could be optimized with bulk insert later
            for event in events:
                await self.publish(event)

            logger.debug("Batch of events published to outbox", event_count=len(events))

        except Exception as e:
            logger.error(
                "Failed to publish batch of events to outbox",
                event_count=len(events),
                error=str(e),
            )
            raise
