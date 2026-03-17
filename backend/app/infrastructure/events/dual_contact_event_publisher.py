"""
Dual contact event publisher for simultaneous real-time and outbox publishing.

Publishes contact domain events to both the real-time async event bus
(for WebSocket notifications) and the transactional outbox (for reliable
MeiliSearch indexing via the search_indexer worker).
"""

from collections.abc import Sequence

from app.core.contacts.adapters.sql import SqlContactEventPublisher
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    DomainEventProtocol,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


class DualContactEventPublisher(ContactEventPublisher):
    """
    Publishes contact events to both the async event bus and the outbox.

    The async (SQL-backed) publisher drives real-time WebSocket updates,
    while the outbox publisher ensures reliable, transactional delivery
    to the search indexer and any future event consumers.
    """

    def __init__(
        self,
        sql_pub: SqlContactEventPublisher,
        outbox_pub: OutboxEventPublisher,
    ):
        self.sql_pub = sql_pub
        self.outbox_pub = outbox_pub

    async def publish(self, event: DomainEventProtocol) -> None:
        await self.sql_pub.publish(event)
        await self.outbox_pub.publish(event)

    async def publish_batch(self, events: Sequence[DomainEventProtocol]) -> None:
        await self.sql_pub.publish_batch(events)
        await self.outbox_pub.publish_batch(events)
