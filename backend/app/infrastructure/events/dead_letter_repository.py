from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.dead_letter_table import dead_letter_events_table


@dataclass
class DeadLetterEvent:
    """A dead-lettered domain event that failed processing."""

    event_id: str
    event_type: str
    aggregate_id: int
    event_data: dict[str, Any]
    consumer_group: str
    delivery_count: int
    last_error: str | None = None
    created_at: datetime | None = None
    id: int | None = None


class DeadLetterRepository:
    """Repository for managing dead-lettered events."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize the repository.

        Args:
            connection: The async database connection
        """
        self._connection = connection

    async def save(self, event: DeadLetterEvent) -> DeadLetterEvent:
        """Save a dead-letter event to the database.

        If the event already exists for this consumer group, it does nothing
        (idempotent insert).

        Args:
            event: The dead-letter event to save

        Returns:
            The saved event
        """
        stmt = (
            insert(dead_letter_events_table)
            .values(
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                event_data=event.event_data,
                consumer_group=event.consumer_group,
                delivery_count=event.delivery_count,
                last_error=event.last_error,
            )
            .on_conflict_do_nothing(constraint="uq_dead_letter_event_consumer")
            .returning(
                dead_letter_events_table.c.id, dead_letter_events_table.c.created_at
            )
        )

        result = await self._connection.execute(stmt)
        row = result.first()

        if row:
            event.id = row.id
            event.created_at = row.created_at

        return event

    async def list_events(
        self, limit: int = 50, offset: int = 0
    ) -> list[DeadLetterEvent]:
        """List dead-letter events, ordered by newest first.

        Args:
            limit: Maximum number of events to return
            offset: Number of events to skip

        Returns:
            List of dead-letter events
        """
        stmt = (
            select(dead_letter_events_table)
            .order_by(dead_letter_events_table.c.id.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self._connection.execute(stmt)
        rows = result.all()

        return [
            DeadLetterEvent(
                id=row.id,
                event_id=row.event_id,
                event_type=row.event_type,
                aggregate_id=row.aggregate_id,
                event_data=row.event_data,
                consumer_group=row.consumer_group,
                delivery_count=row.delivery_count,
                last_error=row.last_error,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Count the total number of dead-letter events.

        Returns:
            Total count
        """
        stmt = select(func.count(dead_letter_events_table.c.id))
        result = await self._connection.execute(stmt)
        return result.scalar_one() or 0
