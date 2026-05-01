"""
Mixin for backend StreamConsumers to persist dead letters to the database.
"""

import structlog
from core_shared.stream_client import PendingEntry, StreamEvent

from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.dead_letter_repository import (
    DeadLetterEvent,
    DeadLetterRepository,
)

logger = structlog.get_logger()


class DeadLetterConsumerMixin:
    """Mixin for StreamConsumer to persist dead letters to the database."""

    async def _handle_dead_letter(
        self, event: StreamEvent, pending_entry: PendingEntry
    ) -> None:
        """Persist dead-letter event to the database and acknowledge it.

        Args:
            event: The stream event that failed
            pending_entry: The pending entry with delivery count
        """
        try:
            engine = get_async_database_engine()
            async with engine.begin() as conn:
                repository = DeadLetterRepository(conn)

                dead_letter = DeadLetterEvent(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    aggregate_id=event.aggregate_id,
                    event_data=event.event_data,
                    consumer_group=self._group_name,  # type: ignore
                    delivery_count=pending_entry.delivery_count,
                    last_error="Exceeded max delivery count",
                )

                await repository.save(dead_letter)

            # Use super() to call the base StreamConsumer._handle_dead_letter
            # which logs the error and ACKs the message
            await super()._handle_dead_letter(event, pending_entry)  # type: ignore
        except Exception:
            # If we fail to save to the dead letter queue, we should NOT ack the message,
            # so we just log and let it stay pending.
            logger.error(
                "Failed to save dead letter event",
                event_id=event.event_id,
                group=self._group_name,  # type: ignore
                exc_info=True,
            )
