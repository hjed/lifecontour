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
    processed_at: datetime | None
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

    async def get_unprocessed_events(
        self, limit: int = 100, max_retry_count: int | None = None
    ) -> list[OutboxEvent]:
        """
        Get unprocessed events from the outbox.

        Args:
            limit: Maximum number of events to retrieve
            max_retry_count: Optional retry threshold for excluding failed events

        Returns:
            List of unprocessed outbox events
        """
        try:
            query_lines = [
                "SELECT id, event_id, event_type, aggregate_id, event_data,",
                "       occurred_at, processed_at, retry_count, created_at",
                "FROM outbox_events",
                "WHERE processed_at IS NULL",
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
                        processed_at=row.processed_at,
                        retry_count=row.retry_count,
                        created_at=row.created_at,
                        relayed_at=getattr(row, "relayed_at", None),
                    )
                )

            logger.debug(
                "Retrieved unprocessed events from outbox", event_count=len(events)
            )

            return events

        except Exception as e:
            logger.error(
                "Failed to retrieve unprocessed events from outbox", error=str(e)
            )
            raise

    async def mark_as_processed(self, event_id: str) -> None:
        """
        Mark an event as processed.

        Args:
            event_id: ID of the event to mark as processed
        """
        try:
            query = text(
                """
                UPDATE outbox_events
                SET processed_at = :processed_at
                WHERE event_id = :event_id
                """
            )

            await self.conn.execute(
                query, {"event_id": event_id, "processed_at": datetime.utcnow()}
            )

            logger.debug("Event marked as processed", event_id=event_id)

        except Exception as e:
            logger.error(
                "Failed to mark event as processed", event_id=event_id, error=str(e)
            )
            raise

    async def increment_retry_count(self, event_id: str) -> None:
        """
        Increment the retry count for a failed event.

        Args:
            event_id: ID of the event to increment retry count
        """
        try:
            query = text(
                """
                UPDATE outbox_events
                SET retry_count = retry_count + 1
                WHERE event_id = :event_id
                """
            )

            await self.conn.execute(query, {"event_id": event_id})

            logger.debug("Event retry count incremented", event_id=event_id)

        except Exception as e:
            logger.error(
                "Failed to increment retry count", event_id=event_id, error=str(e)
            )
            raise

    async def mark_as_failed(self, event_id: str, retry_count: int) -> None:
        """
        Mark an event as failed by setting its retry count to a terminal value.

        Args:
            event_id: ID of the event to mark as failed
            retry_count: Exact retry count value to persist for the terminal failure
        """
        try:
            query = text(
                """
                UPDATE outbox_events
                SET retry_count = :retry_count
                WHERE event_id = :event_id
                """
            )

            await self.conn.execute(
                query,
                {"event_id": event_id, "retry_count": retry_count},
            )

            logger.debug(
                "Event marked as failed",
                event_id=event_id,
                retry_count=retry_count,
            )

        except Exception as e:
            logger.error(
                "Failed to mark event as failed",
                event_id=event_id,
                retry_count=retry_count,
                error=str(e),
            )
            raise

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
                "       occurred_at, processed_at, retry_count, created_at, relayed_at",
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
                        processed_at=row.processed_at,
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
                WHERE event_id = :event_id
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

    async def get_failed_events(self, max_retries: int = 3) -> list[OutboxEvent]:
        """
        Get events that have exceeded the maximum retry count.

        Args:
            max_retries: Maximum number of retries before considering failed

        Returns:
            List of failed outbox events
        """
        try:
            query = text(
                """
                SELECT id, event_id, event_type, aggregate_id, event_data,
                       occurred_at, processed_at, retry_count, created_at
                FROM outbox_events
                WHERE processed_at IS NULL AND retry_count >= :max_retries
                ORDER BY created_at ASC
                """
            )

            result = await self.conn.execute(query, {"max_retries": max_retries})
            rows = result.fetchall()

            events = []
            for row in rows:
                events.append(
                    OutboxEvent(
                        id=row.id,
                        event_id=row.event_id,
                        event_type=row.event_type,
                        aggregate_id=row.aggregate_id,
                        event_data=row.event_data,
                        occurred_at=row.occurred_at,
                        processed_at=row.processed_at,
                        retry_count=row.retry_count,
                        created_at=row.created_at,
                    )
                )

            return events

        except Exception as e:
            logger.error("Failed to retrieve failed events from outbox", error=str(e))
            raise
