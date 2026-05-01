"""
Adapter for converting Redis Stream events to OutboxEvent format.

Provides a utility function to convert StreamEvent (from core_shared)
into OutboxEvent (used by SearchIndexer and other event processors)
for backward compatibility during the stream consumer migration.
"""

from datetime import datetime

from core_shared.stream_client import StreamEvent

from app.infrastructure.events.outbox_repository import OutboxEvent


def stream_event_to_outbox_event(stream_event: StreamEvent) -> OutboxEvent:
    """Convert a StreamEvent to an OutboxEvent for processor compatibility.

    The existing SearchIndexer and summary generation pipeline expect
    OutboxEvent objects. This adapter bridges the two data structures
    so stream consumers can reuse existing processing logic.

    Args:
        stream_event: Event read from Redis Stream

    Returns:
        OutboxEvent with fields mapped from the stream event
    """
    occurred_at = datetime.fromisoformat(stream_event.occurred_at)

    return OutboxEvent(
        id=0,
        event_id=stream_event.event_id,
        event_type=stream_event.event_type,
        aggregate_id=stream_event.aggregate_id,
        event_data=stream_event.event_data,
        occurred_at=occurred_at,
        retry_count=0,
        created_at=occurred_at,
    )
