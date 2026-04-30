"""
Repository for managing outbox events.

Handles retrieval and processing of events from the outbox_events table
for the background processor.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger()


@dataclass
class OutboxEvent:
    """Outbox event data structure."""

    id: int
    event_id: str
    event_type: str
    aggregate_id: int
    event_data: dict[str, Any]
    occurred_at: datetime
    retry_count: int
    created_at: datetime
    relayed_at: datetime | None = None


class OutboxRepository:
    """Repository for outbox event operations."""

    def __init__(self, connection: AsyncConnection):
        """
        Initialize with database connection.

        Args:
            connection: Async database connection
        """
        self.conn = connection

    async def get_unrelayed_events(
        self, limit: int = 100, max_retry_count: int | None = None
    ) -> list[OutboxEvent]:
        """
        Get events that have not yet been relayed to the Redis Stream.

        Args:
            limit: Maximum number of events to retrieve
            max_retry_count: Optional retry threshold for excluding failed events

        Returns:
            List of unrelayed outbox events
        """
        try:
            query_lines = [
                "SELECT id, event_id, event_type, aggregate_id, event_data,",
                "       occurred_at, retry_count, created_at, relayed_at",
                "FROM outbox_events",
                "WHERE relayed_at IS NULL",
            ]
            params: dict[str, Any] = {"limit": limit}

            if max_retry_count is not None:
                query_lines.append("  AND retry_count < :max_retry_count")
                params["max_retry_count"] = max_retry_count

            query_lines.extend(["ORDER BY created_at ASC", "LIMIT :limit"])
            query = text("\n".join(query_lines))

            result = await self.conn.execute(query, params)
            rows = result.fetchall()

            events = []
            for row in rows:
                event_data = row.event_data
                if isinstance(event_data, str):
                    event_data = json.loads(event_data)

                events.append(
                    OutboxEvent(
                        id=row.id,
                        event_id=row.event_id,
                        event_type=row.event_type,
                        aggregate_id=row.aggregate_id,
                        event_data=event_data,
                        occurred_at=row.occurred_at,
                        retry_count=row.retry_count,
                        created_at=row.created_at,
                        relayed_at=row.relayed_at,
                    )
                )

            logger.debug(
                "Retrieved unrelayed events from outbox", event_count=len(events)
            )

            return events

        except Exception as e:
            logger.error(
                "Failed to retrieve unrelayed events from outbox", error=str(e)
            )
            raise

    async def mark_as_relayed(self, event_id: str) -> None:
        """
        Mark an event as relayed to the Redis Stream.

        Args:
            event_id: ID of the event to mark as relayed
        """
        try:
            query = text(
                """
                UPDATE outbox_events
                SET relayed_at = :relayed_at
                WHERE event_id = :event_id AND relayed_at IS NULL
                """
            )

            await self.conn.execute(
                query, {"event_id": event_id, "relayed_at": datetime.now(UTC)}
            )

            logger.debug("Event marked as relayed", event_id=event_id)

        except Exception as e:
            logger.error(
                "Failed to mark event as relayed", event_id=event_id, error=str(e)
            )
            raise
