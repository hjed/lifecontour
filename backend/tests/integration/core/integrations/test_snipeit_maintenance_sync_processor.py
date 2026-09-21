"""Integration tests for Snipe-IT maintenance events in JournalOutboxEventProcessor.

The Snipe-IT worker tells an imported maintenance journal apart from one a
user wrote by the external event link this processor records on the synthetic
maintenance calendar. Without that link the worker would push the import back to
Snipe-IT as a new record, so these tests pin the link as a contract.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
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


def _maintenance_event(
    gear_item_id: str,
    maintenance_id: int,
    *,
    maintenance_type: str = "routine maintenance",
    existing_journal_id: int | None = None,
    title: str = "Split Canyoneroo 50 -> 34 + 15",
    version_hash: str | None = None,
) -> OutboxEvent:
    """A ``journal_event.created``/``.updated`` shaped like the Snipe-IT worker's payload.

    The worker sends only what Snipe-IT records: no ``activity_types`` and no
    ``retirement_reason``.
    """
    sync_action = "created" if existing_journal_id is None else "updated"
    event_data: dict[str, Any] = {
        "integration_source": "snipeit_maintenance",
        "external_event_id": f"snipeit_maint:{maintenance_id}",
        "calendar_id": SNIPEIT_MAINTENANCE_CALENDAR_ID,
        "journal_data": {
            "user_id": USER_ID,
            "title": title,
            "content": "",
            "event_date_range_start": "2026-09-11T00:00:00+00:00",
            "event_date_range_end": "2026-09-11T00:00:00+00:00",
            "gear_maintenance_data": {
                "gear_item_id": gear_item_id,
                "maintenance_type": maintenance_type,
            },
            "journal_types": ["GEAR_MAINTENANCE"],
            "version_hash": version_hash or f"maintenance-hash-{sync_action}",
        },
        "calendar_info_data": {"calendar_id": SNIPEIT_MAINTENANCE_CALENDAR_ID},
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "sync_action": sync_action,
        "existing_journal_id": existing_journal_id,
    }
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=f"journal_event.{sync_action}",
        aggregate_id="0",
        event_data=event_data,
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )


async def _record_sent(connection: AsyncConnection, event: OutboxEvent) -> None:
    """Write the sync row the worker writes in the same transaction as ``event``.

    The worker never enqueues a maintenance event without recording its hash on
    the record's sync row, so the processor can rely on that row saying which
    event for the record is the latest.
    """
    event_data: dict[str, Any] = event.event_data  # type: ignore[assignment]
    await connection.execute(
        text(
            """
            INSERT INTO sync_metadata
                (integration_source, external_id, last_synced_at, version_hash,
                 sync_status, retry_count, created_at, updated_at)
            VALUES
                ('snipeit_maintenance', :external_id, now(), :version_hash,
                 'success', 0, now(), now())
            ON CONFLICT (integration_source, external_id)
            DO UPDATE SET version_hash = EXCLUDED.version_hash
            """
        ),
        {
            "external_id": event_data["external_event_id"],
            "version_hash": event_data["journal_data"]["version_hash"],
        },
    )


async def _send(
    processor: JournalOutboxEventProcessor,
    connection: AsyncConnection,
    event: OutboxEvent,
) -> dict[str, Any]:
    """Send ``event`` as the worker does, then process it straight away."""
    await _record_sent(connection, event)
    return await processor.process_event(event)


async def _import_edited_maintenance(
    connection: AsyncConnection,
    *,
    activity_types: list[str],
    maintenance_type: str = "routine maintenance",
    retirement_reason: str | None = None,
) -> tuple[JournalOutboxEventProcessor, str, int]:
    """Import Snipe-IT maintenance 17, then edit its row as the user would.

    Returns the processor, the gear item id and the imported journal's id.
    """
    gear_item_id = await _create_gear_item(connection)
    processor = build_processor(connection)
    created = await _send(
        processor, connection, _maintenance_event(gear_item_id, maintenance_id=17)
    )
    journal_id = int(created["journal_id"])
    await connection.execute(
        text(
            """
            UPDATE journal_gear_maintenance_data
            SET maintenance_type = :maintenance_type,
                retirement_reason = :retirement_reason,
                activity_types = CAST(:activity_types AS jsonb)
            WHERE journal_id = :journal_id
            """
        ),
        {
            "journal_id": journal_id,
            "maintenance_type": maintenance_type,
            "retirement_reason": retirement_reason,
            "activity_types": json.dumps(activity_types),
        },
    )
    return processor, gear_item_id, journal_id


async def _maintenance_row(connection: AsyncConnection, journal_id: int) -> Any:
    result = await connection.execute(
        text(
            """
            SELECT maintenance_type, activity_types, retirement_reason
            FROM journal_gear_maintenance_data
            WHERE journal_id = :journal_id
            """
        ),
        {"journal_id": journal_id},
    )
    return result.one()


@pytest.mark.integration
class TestSnipeItMaintenanceImportLink:
    async def test_imported_maintenance_is_linked_on_the_maintenance_calendar(
        self, async_connection: AsyncConnection
    ) -> None:
        gear_item_id = await _create_gear_item(async_connection)
        processor = build_processor(async_connection)

        result = await _send(
            processor,
            async_connection,
            _maintenance_event(gear_item_id, maintenance_id=17),
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


@pytest.mark.integration
class TestSnipeItMaintenanceResyncKeepsLocalFields:
    """Snipe-IT has no activity types or retirement reason, so a re-import that
    does not send them leaves the journal's own values alone."""

    async def test_resync_keeps_activity_types_and_applies_the_new_type(
        self, async_connection: AsyncConnection
    ) -> None:
        processor, gear_item_id, journal_id = await _import_edited_maintenance(
            async_connection, activity_types=["canyoning"]
        )

        await _send(
            processor,
            async_connection,
            _maintenance_event(
                gear_item_id,
                maintenance_id=17,
                maintenance_type="upgrading gear",
                existing_journal_id=journal_id,
            ),
        )

        row = await _maintenance_row(async_connection, journal_id)
        assert row.maintenance_type == "upgrading gear"
        assert row.activity_types == ["canyoning"]

    async def test_resync_keeps_the_reason_a_retired_item_was_retired(
        self, async_connection: AsyncConnection
    ) -> None:
        processor, gear_item_id, journal_id = await _import_edited_maintenance(
            async_connection,
            activity_types=["abseiling_trip"],
            maintenance_type="retiring gear",
            retirement_reason="Core shot",
        )

        await _send(
            processor,
            async_connection,
            _maintenance_event(
                gear_item_id,
                maintenance_id=17,
                maintenance_type="retiring gear",
                existing_journal_id=journal_id,
            ),
        )

        row = await _maintenance_row(async_connection, journal_id)
        assert row.maintenance_type == "retiring gear"
        assert row.retirement_reason == "Core shot"
        assert row.activity_types == ["abseiling_trip"]

    async def test_maintenance_data_the_domain_refuses_is_skipped_not_raised(
        self, async_connection: AsyncConnection
    ) -> None:
        """A retirement with no reason anywhere is logged and skipped, so the
        event cannot fail on every retry."""
        gear_item_id = await _create_gear_item(async_connection)
        processor = build_processor(async_connection)

        result = await _send(
            processor,
            async_connection,
            _maintenance_event(
                gear_item_id, maintenance_id=17, maintenance_type="retiring gear"
            ),
        )

        rows = await async_connection.execute(
            text(
                "SELECT 1 FROM journal_gear_maintenance_data"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": result["journal_id"]},
        )
        assert rows.fetchall() == []


async def _journal_titles(connection: AsyncConnection) -> list[str]:
    """The titles of every journal imported from a Snipe-IT maintenance."""
    result = await connection.execute(
        text(
            """
            SELECT j.title
            FROM journals j
            JOIN journal_external_event_links l ON l.journal_id = j.id
            WHERE l.calendar_id = :calendar_id
            ORDER BY j.id
            """
        ),
        {"calendar_id": SNIPEIT_MAINTENANCE_CALENDAR_ID},
    )
    return [row.title for row in result]


@pytest.mark.integration
class TestOnlyTheLatestSnipeItEventApplies:
    """An event a newer one for the same record has replaced is not applied.

    The worker records each event's hash on the record's sync row in the same
    transaction it enqueues the event, so the row always names the latest. The
    stream cannot promise delivery in that order: a create delivered and not
    acknowledged before its consumer died sits in the pending list, and the
    consumer reads new events before it reclaims pending ones. Applying such an
    event late put a record's older state over the journal, and nothing
    corrected it — the row's hash said the journal was already current.
    """

    async def test_an_event_overtaken_by_a_newer_one_is_skipped(
        self, async_connection: AsyncConnection
    ) -> None:
        """The order a consumer outage delivers them in: newest first."""
        gear_item_id = await _create_gear_item(async_connection)
        processor = build_processor(async_connection)
        original = _maintenance_event(
            gear_item_id, maintenance_id=17, version_hash="as-first-imported"
        )
        recovery = _maintenance_event(
            gear_item_id,
            maintenance_id=17,
            title="Re-taped the sheath",
            version_hash="as-edited-in-snipeit",
        )
        # Both were sent, in order; the row names the later one.
        await _record_sent(async_connection, original)
        await _record_sent(async_connection, recovery)

        await processor.process_event(recovery)
        late = await processor.process_event(original)

        assert late["status"] == "skipped"
        assert await _journal_titles(async_connection) == ["Re-taped the sheath"]

    async def test_an_event_for_a_record_no_longer_synced_is_skipped(
        self, async_connection: AsyncConnection
    ) -> None:
        """A record whose row has gone was deleted after its event was sent.

        Applying the event would bring back a journal for a record that is no
        longer in Snipe-IT.
        """
        gear_item_id = await _create_gear_item(async_connection)
        processor = build_processor(async_connection)
        event = _maintenance_event(gear_item_id, maintenance_id=17)
        await _record_sent(async_connection, event)
        await async_connection.execute(
            text(
                "DELETE FROM sync_metadata"
                " WHERE integration_source = 'snipeit_maintenance'"
                "   AND external_id = 'snipeit_maint:17'"
            )
        )

        result = await processor.process_event(event)

        assert result["status"] == "skipped"
        assert await _journal_titles(async_connection) == []
