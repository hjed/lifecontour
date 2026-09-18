"""Outbox rows written directly, for tests that count the outbox backlog."""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def insert_outbox_event(connection: AsyncConnection) -> str:
    """Insert one unrelayed outbox event and return its event id."""
    event_id = f"test-evt-{uuid.uuid4().hex[:8]}"
    await connection.execute(
        text(
            """
            INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data, occurred_at,
                 created_at, retry_count)
            VALUES (:event_id, 'ContactCreated', 42, :event_data, NOW(), NOW(), 0)
            """
        ),
        {"event_id": event_id, "event_data": json.dumps({"contact_id": 42})},
    )
    return event_id


async def relay_everything(connection: AsyncConnection) -> None:
    """Mark every outbox row relayed, so a test counts only the rows it adds.

    The outbox is shared across the session and not every test rolls back what
    it writes there; this runs inside the test's own savepoint, so it is undone
    with the rest of the test.
    """
    await connection.execute(
        text("UPDATE outbox_events SET relayed_at = NOW() WHERE relayed_at IS NULL")
    )
