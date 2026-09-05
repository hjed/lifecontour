"""The inbound sync records the zone an imported event's clock times are in.

``journal_calendar_info.start_time``/``end_time`` are clock-only values local
to the Google event's zone. Without that zone stored alongside them the
outbound push cannot anchor them, and a later edit would re-anchor them in
whatever zone it guessed.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.core.integrations.journal_sync_seeding import (
    build_processor,
    create_calendar,
    sync_event,
)

pytestmark = pytest.mark.integration


async def _stored_timezone(connection: AsyncConnection, journal_id: int) -> str | None:
    result = await connection.execute(
        text("SELECT timezone FROM journal_calendar_info WHERE journal_id = :id"),
        {"id": journal_id},
    )
    return result.scalar()


class TestInboundCalendarInfoTimezone:
    async def test_a_created_event_stores_its_google_zone(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection, name="Work")

        result = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar,
                external_event_id="la-meeting-1",
                timezone="America/Los_Angeles",
            )
        )

        assert result["status"] == "success"
        assert (
            await _stored_timezone(async_connection, result["journal_id"])
            == "America/Los_Angeles"
        )

    async def test_an_updated_event_replaces_the_stored_zone(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection, name="Work")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar,
                external_event_id="moved-meeting-1",
                timezone="America/Los_Angeles",
            )
        )
        journal_id = created["journal_id"]

        updated = await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar,
                external_event_id="moved-meeting-1",
                existing_journal_id=journal_id,
                etag='"etag-2"',
                timezone="Australia/Sydney",
            )
        )

        assert updated["status"] == "success"
        assert (
            await _stored_timezone(async_connection, journal_id) == "Australia/Sydney"
        )
