"""Integration tests for Snipe-IT maintenance events in JournalOutboxEventProcessor.

The Snipe-IT worker tells an imported maintenance journal apart from one a
user wrote by the external event link this processor records on the synthetic
maintenance calendar. Without that link the worker would push the import back to
Snipe-IT as a new record, so these tests pin the link as a contract.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
)

# Must equal ``_SNIPEIT_MAINTENANCE_CALENDAR_ID`` in the Snipe-IT worker.
SNIPEIT_MAINTENANCE_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"


async def _create_gear_item(connection: AsyncConnection) -> str:
    result = await connection.execute(
        text(
            """
            INSERT INTO gear_items (name, user_id)
            VALUES ('Canyoneroo 50m', :user_id)
            RETURNING id
            """
        ),
        {"user_id": USER_ID},
    )
    return str(result.scalar_one())


def _maintenance_created_event(gear_item_id: str, maintenance_id: int) -> OutboxEvent:
    """A ``journal_event.created`` shaped like the Snipe-IT worker's payload."""
    event_data: dict[str, Any] = {
        "integration_source": "snipeit_maintenance",
        "external_event_id": f"snipeit_maint:{maintenance_id}",
        "calendar_id": SNIPEIT_MAINTENANCE_CALENDAR_ID,
        "journal_data": {
            "user_id": USER_ID,
            "title": "Split Canyoneroo 50 -> 34 + 15",
            "content": "",
            "event_date_range_start": "2026-09-11T00:00:00+00:00",
            "event_date_range_end": "2026-09-11T00:00:00+00:00",
            "gear_maintenance_data": {
                "gear_item_id": gear_item_id,
                "maintenance_type": "routine maintenance",
            },
            "journal_types": ["GEAR_MAINTENANCE"],
            "version_hash": "maintenance-hash",
        },
        "calendar_info_data": {"calendar_id": SNIPEIT_MAINTENANCE_CALENDAR_ID},
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "sync_action": "created",
        "existing_journal_id": None,
    }
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type="journal_event.created",
        aggregate_id="0",
        event_data=event_data,
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )


@pytest.mark.integration
class TestSnipeItMaintenanceImportLink:
    async def test_imported_maintenance_is_linked_on_the_maintenance_calendar(
        self, async_connection: AsyncConnection
    ) -> None:
        gear_item_id = await _create_gear_item(async_connection)
        processor = build_processor(async_connection)

        result = await processor.process_event(
            _maintenance_created_event(gear_item_id, maintenance_id=17)
        )

        links = await async_connection.execute(
            text(
                """
                SELECT calendar_id::text AS calendar_id, external_event_id
                FROM journal_external_event_links
                WHERE journal_id = :journal_id
                """
            ),
            {"journal_id": result["journal_id"]},
        )
        assert [tuple(row) for row in links] == [
            (SNIPEIT_MAINTENANCE_CALENDAR_ID, "snipeit_maint:17")
        ]
        maintenance = await async_connection.execute(
            text(
                "SELECT gear_item_id::text FROM journal_gear_maintenance_data"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": result["journal_id"]},
        )
        assert maintenance.scalar_one() == gear_item_id
