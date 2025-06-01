"""SQL implementation of ContactEditEventRepository."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import (
    ContactEditEvent,
    ContactEditEventRepository,
)


class SqlContactEditEventRepository(ContactEditEventRepository):
    """SQL implementation of ContactEditEventRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    def _parse_event_data(self, event_data: Any) -> dict[str, Any]:
        """Parse event data from database row."""
        if isinstance(event_data, dict):
            return event_data
        return json.loads(event_data) if event_data else {}

    async def store_event(self, event: ContactEditEvent) -> ContactEditEvent:
        """Store a contact edit event."""
        query = text(
            """
            INSERT INTO contact_edit_event
            (event_id, event_type, aggregate_id, event_data, occurred_at, correlation_id)
            VALUES (:event_id, :event_type, :aggregate_id, :event_data, :occurred_at, :correlation_id)
            RETURNING id
        """
        )
        # Convert string timestamp to datetime if needed
        occurred_at = event.occurred_at
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            # Convert to naive datetime for PostgreSQL compatibility
            occurred_at = occurred_at.replace(tzinfo=None)

        result = await self.conn.execute(
            query,
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "event_data": json.dumps(event.event_data),
                "occurred_at": occurred_at,
                "correlation_id": event.correlation_id,
            },
        )
        row = result.fetchone()
        event.id = row.id

        return event

    async def get_events_for_contact(
        self, contact_id: int, limit: int = 50
    ) -> list[ContactEditEvent]:
        """Get edit events for a specific contact."""
        query = text(
            """
            SELECT id, event_id, event_type, aggregate_id, event_data, occurred_at, correlation_id
            FROM contact_edit_event
            WHERE aggregate_id = :contact_id
            ORDER BY occurred_at DESC
            LIMIT :limit
        """
        )
        result = await self.conn.execute(
            query, {"contact_id": contact_id, "limit": limit}
        )

        events = []
        for row in result.fetchall():
            # Convert datetime back to ISO string for consistency
            occurred_at = row.occurred_at
            if isinstance(occurred_at, datetime):
                occurred_at = occurred_at.isoformat() + "Z"

            event = ContactEditEvent(
                event_id=row.event_id,
                event_type=row.event_type,
                aggregate_id=row.aggregate_id,
                event_data=self._parse_event_data(row.event_data),
                occurred_at=occurred_at,
                correlation_id=row.correlation_id,
                id=row.id,
            )
            events.append(event)

        return events

    async def get_events_by_type(
        self, event_type: str, limit: int = 50
    ) -> list[ContactEditEvent]:
        """Get events by type."""
        query = text(
            """
            SELECT id, event_id, event_type, aggregate_id, event_data, occurred_at, correlation_id
            FROM contact_edit_event
            WHERE event_type = :event_type
            ORDER BY occurred_at DESC
            LIMIT :limit
        """
        )
        result = await self.conn.execute(
            query, {"event_type": event_type, "limit": limit}
        )

        events = []
        for row in result.fetchall():
            # Convert datetime back to ISO string for consistency
            occurred_at = row.occurred_at
            if isinstance(occurred_at, datetime):
                occurred_at = occurred_at.isoformat() + "Z"

            event = ContactEditEvent(
                event_id=row.event_id,
                event_type=row.event_type,
                aggregate_id=row.aggregate_id,
                event_data=self._parse_event_data(row.event_data),
                occurred_at=occurred_at,
                correlation_id=row.correlation_id,
                id=row.id,
            )
            events.append(event)

        return events

    async def get_events_by_correlation_id(
        self, correlation_id: str, limit: int = 50
    ) -> list[ContactEditEvent]:
        """Get events by correlation ID."""
        query = text(
            """
            SELECT id, event_id, event_type, aggregate_id, event_data, occurred_at, correlation_id
            FROM contact_edit_event
            WHERE correlation_id = :correlation_id
            ORDER BY occurred_at DESC
            LIMIT :limit
        """
        )
        result = await self.conn.execute(
            query, {"correlation_id": correlation_id, "limit": limit}
        )

        events = []
        for row in result.fetchall():
            # Convert datetime back to ISO string for consistency
            occurred_at = row.occurred_at
            if isinstance(occurred_at, datetime):
                occurred_at = occurred_at.isoformat() + "Z"

            event = ContactEditEvent(
                event_id=row.event_id,
                event_type=row.event_type,
                aggregate_id=row.aggregate_id,
                event_data=self._parse_event_data(row.event_data),
                occurred_at=occurred_at,
                correlation_id=row.correlation_id,
                id=row.id,
            )
            events.append(event)

        return events
