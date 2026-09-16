"""
Integration tests for Snipe-IT maintenance sync.

Verifies that maintenance records fetched from the Snipe-IT API are
correctly transformed into outbox events that, when processed, create
GEAR_MAINTENANCE journal entries in the database.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from snipeit_api_client import SnipeItAPIError
from snipeit_models import SnipeItMaintenance
from snipeit_sync_service import IN_FLIGHT_LOCK_SECONDS, SnipeItSyncInProgress

# ``mock_transport``, ``integration_client`` and ``snipeit_sync_service`` are
# shared fixtures defined in ``conftest.py``.


class TestMaintenanceSyncIntegration:
    """Integration tests for Snipe-IT maintenance sync pipeline."""

    @pytest.mark.asyncio
    async def test_sync_maintenance_creates_outbox_event(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify that syncing a maintenance record creates an outbox event.

        Steps:
        1. Create a prerequisite gear item and sync_metadata so the
           asset_id can be resolved to a gear_item_id.
        2. Mock the Snipe-IT maintenance API response.
        3. Run sync_maintenance_batch.
        4. Assert an outbox event was created with the correct data.
        5. Assert sync_metadata was created for the maintenance record.
        """
        # Step 1: Insert a gear item and its sync_metadata (prerequisite)
        gear_item_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Climbing Rope 60m', 'user-123')
                RETURNING id
            """)
        )
        gear_item_row = gear_item_result.fetchone()
        assert gear_item_row is not None
        gear_item_id = str(gear_item_row.id)

        # Create sync_metadata for the asset so the maintenance transformer
        # can resolve asset_id → gear_item_id
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '42', :gear_item_id,
                     now(), 'test-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        # Step 2: Mock Snipe-IT maintenance API response
        maintenance_id = 101
        mock_transport.add_response(
            f"/maintenances/{maintenance_id}",
            json_data={
                "id": maintenance_id,
                "asset": {"id": 42, "name": "Climbing Rope 60m"},
                "title": "Annual Rope Inspection",
                "asset_maintenance_type": "Maintenance",
                "start_date": {"date": "2024-06-01", "formatted": "Jun 01, 2024"},
                "completion_date": {
                    "date": "2024-06-02",
                    "formatted": "Jun 02, 2024",
                },
                "notes": "Inspected rope for damage. All good.",
            },
        )

        # Step 3: Run sync — use a session factory that creates a fresh
        # session joined to the test connection's existing transaction.
        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[maintenance_id],
            session_factory=mock_session_factory,
        )

        assert result["synced"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0

        # Step 4: Verify outbox event was created
        outbox_result = await async_connection.execute(
            text("""
                SELECT event_type, event_data
                FROM outbox_events
                WHERE event_type LIKE 'journal_event.%'
                ORDER BY created_at DESC
                LIMIT 1
            """)
        )
        outbox_row = outbox_result.fetchone()
        assert outbox_row is not None
        assert outbox_row.event_type == "journal_event.created"

        event_data = outbox_row.event_data
        if isinstance(event_data, str):
            event_data = json.loads(event_data)
        assert event_data["integration_source"] == "snipeit_maintenance"
        assert event_data["external_event_id"] == f"snipeit_maint:{maintenance_id}"

        journal_data = event_data["journal_data"]
        assert journal_data["title"] == "Annual Rope Inspection"
        assert "Inspected rope for damage" in journal_data["content"]
        assert journal_data["user_id"] == "user-123"

        # Check gear_maintenance_data
        maintenance_data = journal_data["gear_maintenance_data"]
        assert maintenance_data["gear_item_id"] == gear_item_id
        assert maintenance_data["maintenance_type"] == "routine maintenance"

        # Check journal_types
        assert "GEAR_MAINTENANCE" in journal_data["journal_types"]

        # Step 5: Verify sync_metadata for maintenance
        meta_result = await async_connection.execute(
            text("""
                SELECT version_hash, sync_status
                FROM sync_metadata
                WHERE integration_source = 'snipeit_maintenance'
                  AND external_id = :external_id
            """),
            {"external_id": f"snipeit_maint:{maintenance_id}"},
        )
        meta_row = meta_result.fetchone()
        assert meta_row is not None
        assert meta_row.sync_status == "success"
        assert meta_row.version_hash is not None

    @pytest.mark.asyncio
    async def test_sync_maintenance_dedup_skips_unchanged(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify idempotency: syncing the same maintenance twice is skipped."""
        # Insert prerequisite gear item and sync_metadata
        gear_item_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Harness', 'user-123')
                RETURNING id
            """)
        )
        gear_item_row = gear_item_result.fetchone()
        assert gear_item_row is not None
        gear_item_id = str(gear_item_row.id)

        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '50', :gear_item_id,
                     now(), 'test-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        maintenance_data = {
            "id": 200,
            "asset": {"id": 50, "name": "Harness"},
            "title": "Harness Check",
            "asset_maintenance_type": "PAT Test",
            "start_date": {"date": "2024-07-01", "formatted": "Jul 01, 2024"},
        }

        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        # First sync
        mock_transport.add_response("/maintenances/200", json_data=maintenance_data)

        result1 = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[200],
            session_factory=mock_session_factory,
        )
        assert result1["synced"] == 1

        # Second sync with same data — should be skipped
        mock_transport.add_response("/maintenances/200", json_data=maintenance_data)

        result2 = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[200],
            session_factory=mock_session_factory,
        )
        assert result2["skipped"] == 1
        assert result2["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_maintenance_skips_unsynced_asset(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify maintenance is skipped when the asset has not been synced yet."""
        # No gear item or sync_metadata exists for asset_id=999

        mock_transport.add_response(
            "/maintenances/300",
            json_data={
                "id": 300,
                "asset": {"id": 999, "name": "Unknown Asset"},
                "title": "Unknown Asset Maintenance",
                "asset_maintenance_type": "Repair",
            },
        )

        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[300],
            session_factory=mock_session_factory,
        )

        assert result["skipped"] == 1
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_maintenance_skips_when_no_asset_id(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify maintenance is skipped when API response has no asset_id or asset object."""
        mock_transport.add_response(
            "/maintenances/400",
            json_data={
                "id": 400,
                "title": "Orphan Maintenance",
                "asset_maintenance_type": "Repair",
            },
        )

        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[400],
            session_factory=mock_session_factory,
        )

        assert result["skipped"] == 1
        assert result["synced"] == 0


class TestOutboundMaintenanceSyncIntegration:
    """Integration tests for outbound maintenance sync (app → Snipe-IT)."""

    @pytest.mark.asyncio
    async def test_push_maintenance_create_posts_to_snipeit(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify push_maintenance_create POSTs a new maintenance record to Snipe-IT.

        Steps:
        1. Create prerequisite gear item, journal, maintenance data, and
           asset sync_metadata.
        2. Mock the Snipe-IT POST /maintenances API response.
        3. Run push_maintenance_create.
        4. Assert POST was made (mock consumed).
        5. Assert sync_metadata was created for the maintenance record.
        """
        # Step 1: Insert gear item
        gear_item_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Test Rope', 'user-123')
                RETURNING id
            """)
        )
        gear_item_row = gear_item_result.fetchone()
        assert gear_item_row is not None
        gear_item_id = str(gear_item_row.id)

        # Insert asset sync_metadata (gear_item → Snipe-IT asset 42)
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '42', :gear_item_id,
                     now(), 'test-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        # Insert journal
        journal_result = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Rope Inspection', 'All ropes checked', 'user-123',
                    '2024-06-01', '2024-06-02')
                RETURNING id
            """)
        )
        journal_row = journal_result.fetchone()
        assert journal_row is not None
        journal_id = journal_row.id

        # Insert journal_gear_maintenance_data
        await async_connection.execute(
            text("""
                INSERT INTO journal_gear_maintenance_data
                    (journal_id, gear_item_id, maintenance_type)
                VALUES (:journal_id, :gear_item_id, 'routine inspection')
            """),
            {"journal_id": journal_id, "gear_item_id": gear_item_id},
        )

        # Step 2: Mock Snipe-IT POST response
        mock_transport.add_response(
            "/maintenances",
            method="POST",
            json_data={
                "status": "success",
                "messages": "Asset Maintenance created successfully.",
                "payload": {
                    "id": 501,
                    "asset_id": 42,
                    "title": "Rope Inspection",
                    "asset_maintenance_type": "PAT Test",
                    "start_date": {"date": "2024-06-01"},
                    "completion_date": {"date": "2024-06-02"},
                    "notes": "All ropes checked",
                },
            },
        )

        # Step 3: Build session factory joined to test transaction
        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=mock_session_factory,
        )

        # Step 4: All mock responses consumed (POST was made)
        assert len(mock_transport.responses) == 0

        # Step 5: Verify sync_metadata was created
        meta_result = await async_connection.execute(
            text("""
                SELECT internal_uuid, sync_status
                FROM sync_metadata
                WHERE integration_source = 'snipeit_maintenance'
                  AND external_id = 'snipeit_maint:501'
            """)
        )
        meta_row = meta_result.fetchone()
        assert meta_row is not None
        assert meta_row.internal_uuid == str(journal_id)
        assert meta_row.sync_status == "success"

    @pytest.mark.asyncio
    async def test_push_maintenance_update_patches_snipeit(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify push_maintenance_update PATCHes an existing Snipe-IT maintenance record.

        Steps:
        1. Create gear item, journal, maintenance data, asset + maintenance
           sync_metadata.
        2. Mock the Snipe-IT PATCH /maintenances/501 response.
        3. Run push_maintenance_update.
        4. Assert PATCH was made (mock consumed).
        """
        # Step 1: Insert gear item
        gear_item_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Test Harness', 'user-123')
                RETURNING id
            """)
        )
        gear_item_row = gear_item_result.fetchone()
        assert gear_item_row is not None
        gear_item_id = str(gear_item_row.id)

        # Asset sync_metadata
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '55', :gear_item_id,
                     now(), 'test-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        # Insert journal
        journal_result = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Updated Harness Check', 'Updated notes', 'user-123',
                    '2024-07-01', '2024-07-03')
                RETURNING id
            """)
        )
        journal_row = journal_result.fetchone()
        assert journal_row is not None
        journal_id = journal_row.id

        # Journal gear maintenance data
        await async_connection.execute(
            text("""
                INSERT INTO journal_gear_maintenance_data
                    (journal_id, gear_item_id, maintenance_type)
                VALUES (:journal_id, :gear_item_id, 'repairing gear')
            """),
            {"journal_id": journal_id, "gear_item_id": gear_item_id},
        )

        # Maintenance sync_metadata (journal → snipeit_maint:501)
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit_maintenance', 'snipeit_maint:501', :journal_id,
                     now(), '', 'success',
                     NULL, 0, now(), now())
            """),
            {"journal_id": str(journal_id)},
        )

        # Step 2: Mock Snipe-IT PATCH response
        mock_transport.add_response(
            "/maintenances/501",
            json_data={
                "status": "success",
                "messages": "Asset Maintenance updated successfully.",
                "payload": {
                    "id": 501,
                    "asset_id": 55,
                    "title": "Updated Harness Check",
                    "asset_maintenance_type": "Repair",
                    "start_date": {"date": "2024-07-01"},
                    "completion_date": {"date": "2024-07-03"},
                    "notes": "Updated notes",
                },
            },
        )

        # Step 3
        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        await snipeit_sync_service.push_maintenance_update(
            journal_id=journal_id,
            session_factory=mock_session_factory,
        )

        # Step 4: All mock responses consumed (PATCH was made)
        assert len(mock_transport.responses) == 0


# Synthetic calendar every Snipe-IT maintenance journal is imported into.
_MAINTENANCE_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"

# Maintenance 17 as production Snipe-IT returns it: text HTML-escaped on output.
_SNIPEIT_MAINTENANCE_17: dict[str, Any] = {
    "id": 17,
    "asset": {"id": 51, "name": "Canyoneroo 50m"},
    "title": "Split Canyoneroo 50 -&gt; 34 + 15",
    "asset_maintenance_type": "Configuration Change",
    "start_date": {"date": "2026-09-11", "formatted": "2026-09-11"},
    "completion_date": {"date": "2026-09-11", "formatted": "2026-09-11"},
    "notes": None,
}


def _joined_session_factory(async_connection: AsyncConnection) -> Any:
    """Sessions that join the test transaction through a savepoint."""

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    return session_factory


async def _seed_synced_asset(async_connection: AsyncConnection, asset_id: int) -> str:
    """A gear item already imported from Snipe-IT asset ``asset_id``."""
    result = await async_connection.execute(
        text("""
            INSERT INTO gear_items (name, user_id)
            VALUES ('Canyoneroo 50m', 'user-123')
            RETURNING id
        """)
    )
    gear_item_id = str(result.scalar_one())
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, internal_uuid, last_synced_at,
                 version_hash, sync_status, retry_count, created_at, updated_at)
            VALUES
                ('snipeit', :external_id, :gear_item_id, now(),
                 'asset-hash', 'success', 0, now(), now())
        """),
        {"external_id": str(asset_id), "gear_item_id": gear_item_id},
    )
    return gear_item_id


async def _seed_maintenance_journal(
    async_connection: AsyncConnection,
    *,
    gear_item_id: str,
    title: str,
    imported_from: int | None = None,
    maintenance_type: str = "routine maintenance",
    retirement_reason: str | None = None,
) -> int:
    """A GEAR_MAINTENANCE journal, written as the backend's outbox processor does.

    With ``imported_from`` the journal is the import of that Snipe-IT maintenance:
    it sits on the synthetic maintenance calendar and carries the external event
    link the processor creates. Without it the journal was entered by the user.
    """
    result = await async_connection.execute(
        text("""
            INSERT INTO journals (title, content, user_id,
                event_date_range_start, event_date_range_end)
            VALUES (:title, '', 'user-123', '2026-09-11', '2026-09-11')
            RETURNING id
        """),
        {"title": title},
    )
    journal_id = int(result.scalar_one())
    await async_connection.execute(
        text("""
            INSERT INTO journal_gear_maintenance_data
                (journal_id, gear_item_id, maintenance_type, retirement_reason)
            VALUES (:journal_id, :gear_item_id, :maintenance_type,
                    :retirement_reason)
        """),
        {
            "journal_id": journal_id,
            "gear_item_id": gear_item_id,
            "maintenance_type": maintenance_type,
            "retirement_reason": retirement_reason,
        },
    )
    if imported_from is not None:
        await async_connection.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color)
                VALUES (:calendar_id, 'user-123', 'Snipeit_Maintenance Calendar',
                        '#808080')
                ON CONFLICT (id) DO NOTHING
            """),
            {"calendar_id": _MAINTENANCE_CALENDAR_ID},
        )
        await async_connection.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, :external_event_id,
                        'bidirectional', 'synced')
            """),
            {
                "journal_id": journal_id,
                "calendar_id": _MAINTENANCE_CALENDAR_ID,
                "external_event_id": f"snipeit_maint:{imported_from}",
            },
        )
    return journal_id


async def _seed_push_record(
    async_connection: AsyncConnection, *, journal_id: int, maintenance_id: int
) -> None:
    """The sync row a push writes after creating a Snipe-IT maintenance."""
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (internal_uuid, integration_source, external_id, last_synced_at,
                 version_hash, sync_status, retry_count, created_at, updated_at)
            VALUES
                (:journal_id, 'snipeit_maintenance', :external_id, now(),
                 'payload-hash', 'success', 0, now(), now())
        """),
        {
            "journal_id": str(journal_id),
            "external_id": f"snipeit_maint:{maintenance_id}",
        },
    )


def _snipeit_writes(mock_transport: Any) -> list[str]:
    """Every request that would have changed Snipe-IT, as ``METHOD path``."""
    return [
        f"{request.method} {request.url.path}"
        for request in mock_transport.requests
        if request.method != "GET"
    ]


def _write_response(maintenance_id: int) -> dict[str, Any]:
    """A successful POST/PATCH response, queued so a stray write cannot error out."""
    return {
        "status": "success",
        "payload": {"id": maintenance_id, "asset_id": 51, "title": "echo"},
    }


class TestMaintenanceEchoPrevention:
    """An inbound maintenance must never come back to Snipe-IT as a new record."""

    @pytest.mark.asyncio
    async def test_imported_maintenance_journal_is_not_pushed_back(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        session_factory = _joined_session_factory(async_connection)
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        mock_transport.add_response(
            "/maintenances/17", json_data=_SNIPEIT_MAINTENANCE_17
        )

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[17], session_factory=session_factory
        )
        assert result == {"synced": 1, "skipped": 0, "failed": 0}

        event_row = (
            await async_connection.execute(
                text("""
                    SELECT event_data FROM outbox_events
                    WHERE event_type = 'journal_event.created'
                """)
            )
        ).one()
        event_data = event_row.event_data
        if isinstance(event_data, str):
            event_data = json.loads(event_data)
        imported_title = event_data["journal_data"]["title"]
        # Decoded once on the way in, so a write-back could not double-escape it.
        assert imported_title == "Split Canyoneroo 50 -> 34 + 15"

        # The backend turns the event into this journal and publishes JournalCreated.
        journal_id = await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title=imported_title,
            imported_from=17,
        )
        mock_transport.add_response("/maintenances", json_data=_write_response(20))

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id, session_factory=session_factory
        )

        assert _snipeit_writes(mock_transport) == []
        pushed = await async_connection.execute(
            text("""
                SELECT external_id FROM sync_metadata
                WHERE integration_source = 'snipeit_maintenance'
                  AND internal_uuid = :journal_id
            """),
            {"journal_id": str(journal_id)},
        )
        assert pushed.fetchall() == []

    @pytest.mark.asyncio
    async def test_echoed_import_update_patches_the_original_not_the_echo(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """An import already echoed carries the echo's push row; its edits go to the
        record it was imported from."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15",
            imported_from=17,
        )
        await _seed_push_record(
            async_connection, journal_id=journal_id, maintenance_id=20
        )
        mock_transport.add_response("/maintenances/17", json_data=_write_response(17))
        mock_transport.add_response("/maintenances/20", json_data=_write_response(20))

        await snipeit_sync_service.push_maintenance_update(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert _snipeit_writes(mock_transport) == ["PATCH /api/v1/maintenances/17"]

    @pytest.mark.asyncio
    async def test_inbound_sync_skips_maintenance_pushed_from_journal(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A record we created from a user's journal is that journal, not a new import."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_push_record(
            async_connection, journal_id=journal_id, maintenance_id=8
        )
        mock_transport.add_response(
            "/maintenances/8",
            json_data={**_SNIPEIT_MAINTENANCE_17, "id": 8, "title": "Retire Harness"},
        )

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[8],
            session_factory=_joined_session_factory(async_connection),
        )

        assert result == {"synced": 0, "skipped": 1, "failed": 0}
        events = await async_connection.execute(
            text("SELECT 1 FROM outbox_events WHERE event_type LIKE 'journal_event.%'")
        )
        assert events.fetchall() == []

    @pytest.mark.asyncio
    async def test_resync_after_import_makes_no_snipeit_writes(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        session_factory = _joined_session_factory(async_connection)
        gear_item_id = await _seed_synced_asset(async_connection, 51)

        mock_transport.add_response(
            "/maintenances/17", json_data=_SNIPEIT_MAINTENANCE_17
        )
        await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[17], session_factory=session_factory
        )
        journal_id = await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15",
            imported_from=17,
        )
        # Responses match by URL substring, so the re-sync's GET is queued ahead
        # of the write response a regressed push would consume.
        mock_transport.add_response(
            "/maintenances/17", json_data=_SNIPEIT_MAINTENANCE_17
        )
        mock_transport.add_response("/maintenances", json_data=_write_response(20))
        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id, session_factory=session_factory
        )

        second = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[17], session_factory=session_factory
        )

        assert second == {"synced": 0, "skipped": 1, "failed": 0}
        assert _snipeit_writes(mock_transport) == []


async def _seed_import_record(
    async_connection: AsyncConnection, *, maintenance_id: int, version_hash: str
) -> None:
    """The sync row an import writes: the record's hash and no journal id."""
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, last_synced_at,
                 version_hash, sync_status, retry_count, created_at, updated_at)
            VALUES
                ('snipeit_maintenance', :external_id, now(),
                 :version_hash, 'success', 0, now(), now())
        """),
        {
            "external_id": f"snipeit_maint:{maintenance_id}",
            "version_hash": version_hash,
        },
    )


async def _updated_event_maintenance_type(async_connection: AsyncConnection) -> str:
    """The maintenance type the one ``journal_event.updated`` would apply."""
    row = (
        await async_connection.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'journal_event.updated'
            """)
        )
    ).one()
    event_data = row.event_data
    if isinstance(event_data, str):
        event_data = json.loads(event_data)
    return str(event_data["journal_data"]["gear_maintenance_data"]["maintenance_type"])


class TestInboundMaintenanceTypeIsLossless:
    """A re-import neither collapses a Snipe-IT kind nor loses an app-only type."""

    @pytest.mark.asyncio
    async def test_resync_keeps_retiring_gear_that_snipeit_records_as_maintenance(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        session_factory = _joined_session_factory(async_connection)
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        record = {**_SNIPEIT_MAINTENANCE_17, "asset_maintenance_type": "Maintenance"}
        mock_transport.add_response("/maintenances/17", json_data=record)
        await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[17], session_factory=session_factory
        )
        # The user retired the item on the imported journal; the push that
        # followed could only tell Snipe-IT "Maintenance".
        await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15",
            imported_from=17,
            maintenance_type="retiring gear",
            retirement_reason="Core shot",
        )
        mock_transport.add_response(
            "/maintenances/17", json_data={**record, "notes": "Retired after the trip"}
        )

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[17], session_factory=session_factory
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert (
            await _updated_event_maintenance_type(async_connection) == "retiring gear"
        )

    @pytest.mark.asyncio
    async def test_resync_corrects_a_type_an_earlier_mapping_collapsed(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """An import synced before types were lossless is re-synced even though
        the record itself has not changed since."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        record = {**_SNIPEIT_MAINTENANCE_17, "asset_maintenance_type": "Upgrade"}
        await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15",
            imported_from=17,
            maintenance_type="routine maintenance",
        )
        legacy_hash = hashlib.sha256(
            SnipeItMaintenance.model_validate(record).model_dump_json().encode()
        ).hexdigest()
        await _seed_import_record(
            async_connection, maintenance_id=17, version_hash=legacy_hash
        )
        mock_transport.add_response("/maintenances/17", json_data=record)

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[17],
            session_factory=_joined_session_factory(async_connection),
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert (
            await _updated_event_maintenance_type(async_connection) == "upgrading gear"
        )


def _patch_bodies(mock_transport: Any) -> list[dict[str, Any]]:
    """The JSON body of every PATCH sent to Snipe-IT, in order."""
    return [
        json.loads(request.content)
        for request in mock_transport.requests
        if request.method == "PATCH"
    ]


async def _imported_event_dates(
    async_connection: AsyncConnection,
) -> tuple[datetime, datetime]:
    """The date range the one ``journal_event.created`` imports a record with."""
    row = (
        await async_connection.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'journal_event.created'
            """)
        )
    ).one()
    event_data = row.event_data
    if isinstance(event_data, str):
        event_data = json.loads(event_data)
    journal_data = event_data["journal_data"]
    return (
        datetime.fromisoformat(journal_data["event_date_range_start"]),
        datetime.fromisoformat(journal_data["event_date_range_end"]),
    )


class TestImportedMaintenanceEditsArePushed:
    """A user's edit to an imported maintenance journal updates the record it
    was imported from."""

    @pytest.mark.asyncio
    async def test_edit_patches_the_imported_record_with_its_own_kind(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15 (checked)",
            imported_from=17,
            maintenance_type="configuration change",
        )
        mock_transport.add_response("/maintenances/17", json_data=_write_response(17))

        await snipeit_sync_service.push_maintenance_update(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert _snipeit_writes(mock_transport) == ["PATCH /api/v1/maintenances/17"]
        assert _patch_bodies(mock_transport) == [
            {
                "name": "Split Canyoneroo 50 -> 34 + 15 (checked)",
                "notes": "",
                "asset_maintenance_type": "Configuration Change",
                "start_date": "2026-09-11",
                "completion_date": "2026-09-11",
            }
        ]
        pushed = await async_connection.execute(
            text("""
                SELECT 1 FROM sync_metadata
                WHERE integration_source = 'snipeit_maintenance'
                  AND internal_uuid = :journal_id
            """),
            {"journal_id": str(journal_id)},
        )
        assert pushed.fetchall() == []

    @pytest.mark.asyncio
    async def test_imported_dates_round_trip_for_a_user_west_of_utc(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Pushing an untouched date must not move it a day earlier."""
        session_factory = _joined_session_factory(async_connection)
        await async_connection.execute(
            text("""
                INSERT INTO user_settings (user_id, timezone)
                VALUES ('user-123', 'America/Los_Angeles')
            """)
        )
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        mock_transport.add_response(
            "/maintenances/17", json_data=_SNIPEIT_MAINTENANCE_17
        )
        await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[17], session_factory=session_factory
        )
        # The backend turns the import into this journal, with the event's dates.
        journal_id = await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15",
            imported_from=17,
            maintenance_type="configuration change",
        )
        start, end = await _imported_event_dates(async_connection)
        await async_connection.execute(
            text("""
                UPDATE journals
                SET event_date_range_start = :start,
                    event_date_range_end = :end
                WHERE id = :journal_id
            """),
            {"start": start, "end": end, "journal_id": journal_id},
        )
        mock_transport.add_response("/maintenances/17", json_data=_write_response(17))

        await snipeit_sync_service.push_maintenance_update(
            journal_id=journal_id, session_factory=session_factory
        )

        [body] = _patch_bodies(mock_transport)
        assert body["start_date"] == "2026-09-11"
        assert body["completion_date"] == "2026-09-11"


# The claim ``_seed_maintenance_journal``'s journal titled "Retire Harness" makes
# on asset 51.
_RETIRE_HARNESS_CLAIM = {
    "asset_id": 51,
    "title": "Retire Harness",
    "start_date": "2026-09-11",
}


async def _seed_claim(
    async_connection: AsyncConnection,
    *,
    journal_id: int,
    status: str,
    age_seconds: int = 0,
) -> None:
    """A claim an earlier push of ``journal_id`` left, last touched ``age_seconds`` ago."""
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (internal_uuid, integration_source, external_id, last_synced_at,
                 version_hash, sync_status, retry_count, reference_data,
                 created_at, updated_at)
            VALUES
                (:journal_id, 'snipeit_maintenance_claim', :journal_id, now(),
                 'PENDING', :status, 0, :reference_data, now(),
                 now() - CAST(:age_seconds AS integer) * interval '1 second')
        """),
        {
            "journal_id": str(journal_id),
            "status": status,
            "age_seconds": age_seconds,
            "reference_data": json.dumps(_RETIRE_HARNESS_CLAIM),
        },
    )


async def _claim_row(async_connection: AsyncConnection, journal_id: int) -> Any:
    """The journal's maintenance claim, or ``None``."""
    result = await async_connection.execute(
        text("""
            SELECT sync_status, reference_data
            FROM sync_metadata
            WHERE integration_source = 'snipeit_maintenance_claim'
              AND external_id = :journal_id
        """),
        {"journal_id": str(journal_id)},
    )
    return result.fetchone()


async def _push_rows(async_connection: AsyncConnection, journal_id: int) -> list[str]:
    """The external ids of the Snipe-IT records the journal is linked to."""
    result = await async_connection.execute(
        text("""
            SELECT external_id
            FROM sync_metadata
            WHERE integration_source = 'snipeit_maintenance'
              AND internal_uuid = :journal_id
            ORDER BY external_id
        """),
        {"journal_id": str(journal_id)},
    )
    return [row.external_id for row in result.fetchall()]


class TestMaintenanceCreateClaim:
    """A push claims the record it creates before posting, so an attempt that
    fails after the POST leaves a claim for its retry and the inbound sync."""

    @pytest.mark.asyncio
    async def test_claim_is_written_before_the_post_and_kept_when_it_fails(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        claims_at_post: list[Any] = []
        serve = mock_transport.handle_async_request

        async def record_claim_then_serve(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                claims_at_post.append(await _claim_row(async_connection, journal_id))
            return await serve(request)

        monkeypatch.setattr(
            mock_transport, "handle_async_request", record_claim_then_serve
        )
        # Snipe-IT created the record, but the response lost its payload.
        mock_transport.add_response(
            "/maintenances", json_data={"status": "success"}, method="POST"
        )

        with pytest.raises(SnipeItAPIError):
            await snipeit_sync_service.push_maintenance_create(
                journal_id=journal_id,
                session_factory=_joined_session_factory(async_connection),
            )

        [claim_at_post] = claims_at_post
        assert claim_at_post.sync_status == "pending"
        assert json.loads(claim_at_post.reference_data) == _RETIRE_HARNESS_CLAIM
        claim = await _claim_row(async_connection, journal_id)
        assert claim.sync_status == "failed"
        assert json.loads(claim.reference_data) == _RETIRE_HARNESS_CLAIM
        assert await _push_rows(async_connection, journal_id) == []

    @pytest.mark.asyncio
    async def test_recorded_push_replaces_the_claim(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(8), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert await _claim_row(async_connection, journal_id) is None
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:8"]

    @pytest.mark.asyncio
    async def test_rejected_post_releases_the_claim(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        mock_transport.add_response(
            "/maintenances", status_code=404, json_data={}, method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert await _claim_row(async_connection, journal_id) is None
        assert await _push_rows(async_connection, journal_id) == []

    @pytest.mark.asyncio
    async def test_a_claim_in_flight_defers_the_push(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Another worker may be posting this journal's record right now."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_claim(async_connection, journal_id=journal_id, status="pending")
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(8), method="POST"
        )

        with pytest.raises(SnipeItSyncInProgress):
            await snipeit_sync_service.push_maintenance_create(
                journal_id=journal_id,
                session_factory=_joined_session_factory(async_connection),
            )

        assert mock_transport.requests == []
        claim = await _claim_row(async_connection, journal_id)
        assert claim.sync_status == "pending"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "age_seconds"),
        [("pending", IN_FLIGHT_LOCK_SECONDS + 1), ("failed", 0)],
        ids=["abandoned", "failed"],
    )
    async def test_a_claim_no_longer_in_flight_is_retaken(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        status: str,
        age_seconds: int,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_claim(
            async_connection,
            journal_id=journal_id,
            status=status,
            age_seconds=age_seconds,
        )
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(8), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert _snipeit_writes(mock_transport) == ["POST /api/v1/maintenances"]
        assert await _claim_row(async_connection, journal_id) is None
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:8"]


def _listed(
    maintenance_id: int, *, title: str = "Retire Harness", asset_id: int = 51
) -> dict[str, Any]:
    """A ``GET /maintenances`` row, dated like ``_seed_maintenance_journal``."""
    return {
        "id": maintenance_id,
        "asset": {"id": asset_id, "name": "Canyoneroo 50m"},
        "title": title,
        "asset_maintenance_type": "Maintenance",
        "start_date": {"date": "2026-09-11", "formatted": "2026-09-11"},
        "completion_date": {"date": "2026-09-11", "formatted": "2026-09-11"},
        "notes": "",
    }


def _queue_maintenance_page(
    mock_transport: Any, *rows: dict[str, Any], total: int | None = None
) -> None:
    """Serve one page of ``GET /maintenances``; pages are served in queue order."""
    mock_transport.add_response(
        "/maintenances?",
        json_data={"total": len(rows) if total is None else total, "rows": list(rows)},
        method="GET",
    )


async def _held_by_an_import(async_connection: AsyncConnection) -> None:
    await _seed_import_record(async_connection, maintenance_id=9, version_hash="h")


async def _held_by_another_journals_push(async_connection: AsyncConnection) -> None:
    await _seed_push_record(async_connection, journal_id=999999, maintenance_id=9)


class TestMaintenanceCreateLinksAClaimedRecord:
    """A push links a matching record no one holds instead of posting a copy of
    it, so a retry after a lost response records one maintenance, not two."""

    @pytest.mark.asyncio
    async def test_retry_links_the_record_a_lost_response_created(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        session_factory = _joined_session_factory(async_connection)
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15",
        )
        # Snipe-IT created record 9, but the response lost its payload.
        mock_transport.add_response(
            "/maintenances", json_data={"status": "success"}, method="POST"
        )
        with pytest.raises(SnipeItAPIError):
            await snipeit_sync_service.push_maintenance_create(
                journal_id=journal_id, session_factory=session_factory
            )
        _queue_maintenance_page(
            mock_transport, _listed(9, title="Split Canyoneroo 50 -&gt; 34 + 15")
        )
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id, session_factory=session_factory
        )

        assert _snipeit_writes(mock_transport) == ["POST /api/v1/maintenances"]
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:9"]
        assert await _claim_row(async_connection, journal_id) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hold",
        [_held_by_an_import, _held_by_another_journals_push],
        ids=["import", "another-journals-push"],
    )
    async def test_a_record_already_held_is_not_linked(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        hold: Callable[[AsyncConnection], Awaitable[None]],
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await hold(async_connection)
        _queue_maintenance_page(mock_transport, _listed(9))
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:10"]

    @pytest.mark.asyncio
    async def test_a_record_matching_another_journals_claim_is_not_linked(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Record 9 may be the one the other journal's failed attempt created."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        other_journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_claim(
            async_connection, journal_id=other_journal_id, status="failed"
        )
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        _queue_maintenance_page(mock_transport, _listed(9))
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:10"]
        other_claim = await _claim_row(async_connection, other_journal_id)
        assert other_claim.sync_status == "failed"

    @pytest.mark.asyncio
    async def test_retry_after_an_edit_links_the_record_its_claim_describes(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The failed attempt posted "Retire Harness"; the journal was retitled since,
        and that edit found no sync row to send it to."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Frayed Harness"
        )
        await _seed_claim(async_connection, journal_id=journal_id, status="failed")
        _queue_maintenance_page(mock_transport, _listed(9))
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )
        mock_transport.add_response(
            "/maintenances/9", json_data=_write_response(9), method="PATCH"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert _snipeit_writes(mock_transport) == ["PATCH /api/v1/maintenances/9"]
        [body] = _patch_bodies(mock_transport)
        assert body["name"] == "Retire Frayed Harness"
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:9"]
        assert await _claim_row(async_connection, journal_id) is None

    @pytest.mark.asyncio
    async def test_a_redelivered_push_sends_the_edits_its_record_missed(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A link whose update failed is retried with the redelivered event, and a
        record already holding the journal's values is left alone."""
        session_factory = _joined_session_factory(async_connection)
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Frayed Harness"
        )
        # The push row a link wrote, with the hash of the record's older values.
        await _seed_push_record(
            async_connection, journal_id=journal_id, maintenance_id=9
        )
        mock_transport.add_response(
            "/maintenances/9", json_data=_write_response(9), method="PATCH"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id, session_factory=session_factory
        )
        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id, session_factory=session_factory
        )

        assert _snipeit_writes(mock_transport) == ["PATCH /api/v1/maintenances/9"]
        [body] = _patch_bodies(mock_transport)
        assert body["name"] == "Retire Frayed Harness"

    @pytest.mark.asyncio
    async def test_a_recorded_journal_is_not_searched_for_again(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A redelivered JournalCreated whose record exists must not fail on a
        Snipe-IT outage the search would meet."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_push_record(
            async_connection, journal_id=journal_id, maintenance_id=9
        )
        mock_transport.add_response(
            "/maintenances?", status_code=500, json_data={}, method="GET"
        )
        mock_transport.add_response(
            "/maintenances/9", json_data=_write_response(9), method="PATCH"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert [r.url.path for r in mock_transport.requests if r.method == "GET"] == []

    @pytest.mark.asyncio
    async def test_a_match_on_a_later_page_is_linked(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        _queue_maintenance_page(
            mock_transport,
            *(_listed(100 + n, title=f"Inspection {n}") for n in range(50)),
            total=51,
        )
        _queue_maintenance_page(mock_transport, _listed(9), total=51)
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert _snipeit_writes(mock_transport) == []
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:9"]

    @pytest.mark.asyncio
    async def test_an_unreadable_maintenance_list_falls_back_to_posting(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        mock_transport.add_response(
            "/maintenances?", status_code=403, json_data={}, method="GET"
        )
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:10"]


async def _journal_events(async_connection: AsyncConnection) -> list[str]:
    """The journal outbox events an inbound sync wrote."""
    result = await async_connection.execute(
        text("""
            SELECT event_type FROM outbox_events
            WHERE event_type LIKE 'journal_event.%'
        """)
    )
    return [row.event_type for row in result.fetchall()]


class TestInboundSyncHonoursMaintenanceClaims:
    """A full maintenance sync links a record a journal's push claims to that
    journal instead of importing it as a second journal."""

    @pytest.mark.asyncio
    async def test_full_sync_links_a_claimed_record_instead_of_importing_it(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        session_factory = _joined_session_factory(async_connection)
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection,
            gear_item_id=gear_item_id,
            title="Split Canyoneroo 50 -> 34 + 15",
        )
        # Snipe-IT created record 9, but the response lost its payload.
        mock_transport.add_response(
            "/maintenances", json_data={"status": "success"}, method="POST"
        )
        with pytest.raises(SnipeItAPIError):
            await snipeit_sync_service.push_maintenance_create(
                journal_id=journal_id, session_factory=session_factory
            )
        mock_transport.add_response(
            "/maintenances/9",
            json_data=_listed(9, title="Split Canyoneroo 50 -&gt; 34 + 15"),
        )

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[9], session_factory=session_factory
        )

        assert result == {"synced": 0, "skipped": 1, "failed": 0}
        assert await _journal_events(async_connection) == []
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:9"]
        assert await _claim_row(async_connection, journal_id) is None

        # The redelivered JournalCreated then finds the record already recorded.
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )
        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id, session_factory=session_factory
        )
        assert _snipeit_writes(mock_transport) == ["POST /api/v1/maintenances"]

    @pytest.mark.asyncio
    async def test_a_record_several_claims_match_is_left_for_a_later_sync(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Either journal's failed attempt may have created record 9."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_ids = [
            await _seed_maintenance_journal(
                async_connection, gear_item_id=gear_item_id, title="Retire Harness"
            )
            for _ in range(2)
        ]
        for journal_id in journal_ids:
            await _seed_claim(async_connection, journal_id=journal_id, status="failed")
        mock_transport.add_response("/maintenances/9", json_data=_listed(9))

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[9],
            session_factory=_joined_session_factory(async_connection),
        )

        assert result == {"synced": 0, "skipped": 1, "failed": 0}
        assert await _journal_events(async_connection) == []
        assert [
            await _push_rows(async_connection, journal_id) for journal_id in journal_ids
        ] == [[], []]
        assert [
            (await _claim_row(async_connection, journal_id)).sync_status
            for journal_id in journal_ids
        ] == ["failed", "failed"]

    @pytest.mark.asyncio
    async def test_another_users_claim_does_not_stop_an_import(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        await _seed_synced_asset(async_connection, 51)
        other_users_journal = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Retire Harness', '', 'other-user', '2026-09-11', '2026-09-11')
                RETURNING id
            """)
        )
        await _seed_claim(
            async_connection,
            journal_id=int(other_users_journal.scalar_one()),
            status="failed",
        )
        mock_transport.add_response("/maintenances/9", json_data=_listed(9))

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[9],
            session_factory=_joined_session_factory(async_connection),
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert await _journal_events(async_connection) == ["journal_event.created"]

    @pytest.mark.asyncio
    async def test_a_record_linked_during_the_post_is_not_recorded_twice(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The push missed record 9, e.g. beyond the pages it searches, and a full
        sync links it to the journal while the push's own POST is in flight."""
        session_factory = _joined_session_factory(async_connection)
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        serve = mock_transport.handle_async_request

        async def sync_then_serve(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                await snipeit_sync_service.sync_maintenance_batch(
                    maintenance_ids=[9], session_factory=session_factory
                )
            return await serve(request)

        monkeypatch.setattr(mock_transport, "handle_async_request", sync_then_serve)
        mock_transport.add_response("/maintenances/9", json_data=_listed(9))
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(10), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id, session_factory=session_factory
        )

        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:9"]
        assert await _claim_row(async_connection, journal_id) is None

    @pytest.mark.asyncio
    async def test_a_claim_of_a_journal_already_recorded_is_spent(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A claim left beside a journal's record cannot link a second record to it."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_push_record(
            async_connection, journal_id=journal_id, maintenance_id=8
        )
        await _seed_claim(async_connection, journal_id=journal_id, status="failed")
        mock_transport.add_response("/maintenances/9", json_data=_listed(9))

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[9],
            session_factory=_joined_session_factory(async_connection),
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert await _journal_events(async_connection) == ["journal_event.created"]
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:8"]
