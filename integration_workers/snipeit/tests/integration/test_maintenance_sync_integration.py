"""
Integration tests for Snipe-IT maintenance sync.

Verifies that maintenance records fetched from the Snipe-IT API are
correctly transformed into outbox events that, when processed, create
GEAR_MAINTENANCE journal entries in the database.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from snipeit_api_client import SnipeItAPIClient
from snipeit_sync_service import SnipeItSyncService


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.responses: list[tuple[str, int, object, dict[str, str]]] = []

    def add_response(
        self,
        url_pattern: str,
        status_code: int = 200,
        json_data: object = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.responses.append((url_pattern, status_code, json_data, headers or {}))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for i, (pattern, status, data, hdrs) in enumerate(self.responses):
            if pattern in url:
                self.responses.pop(i)
                content = json.dumps(data).encode() if data is not None else b""
                return httpx.Response(
                    status_code=status,
                    content=content,
                    headers={**hdrs, "content-type": "application/json"},
                    request=request,
                )
        raise ValueError(f"No mock response configured for {url}")


@pytest.fixture
def mock_transport() -> MockTransport:
    return MockTransport()


@pytest.fixture
def integration_client(mock_transport: MockTransport) -> SnipeItAPIClient:
    client = SnipeItAPIClient.create(
        base_url="https://snipeit.example.com/api/v1/",
        access_token="test-access-token",
        on_token_refresh=AsyncMock(return_value="new-token"),
    )
    client._client = httpx.AsyncClient(
        transport=mock_transport,
        base_url="https://snipeit.example.com/api/v1/",
        headers={"Authorization": "Bearer test-access-token"},
    )
    return client


@pytest.fixture
def sync_service(integration_client: SnipeItAPIClient) -> SnipeItSyncService:
    return SnipeItSyncService(
        api_client=integration_client,
        user_id="user-123",
    )


class TestMaintenanceSyncIntegration:
    """Integration tests for Snipe-IT maintenance sync pipeline."""

    @pytest.mark.asyncio
    async def test_sync_maintenance_creates_outbox_event(
        self,
        sync_service: SnipeItSyncService,
        mock_transport: MockTransport,
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
                "asset_id": 42,
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

        result = await sync_service.sync_maintenance_batch(
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
        sync_service: SnipeItSyncService,
        mock_transport: MockTransport,
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
            "asset_id": 50,
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

        result1 = await sync_service.sync_maintenance_batch(
            maintenance_ids=[200],
            session_factory=mock_session_factory,
        )
        assert result1["synced"] == 1

        # Second sync with same data — should be skipped
        mock_transport.add_response("/maintenances/200", json_data=maintenance_data)

        result2 = await sync_service.sync_maintenance_batch(
            maintenance_ids=[200],
            session_factory=mock_session_factory,
        )
        assert result2["skipped"] == 1
        assert result2["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_maintenance_skips_unsynced_asset(
        self,
        sync_service: SnipeItSyncService,
        mock_transport: MockTransport,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify maintenance is skipped when the asset has not been synced yet."""
        # No gear item or sync_metadata exists for asset_id=999

        mock_transport.add_response(
            "/maintenances/300",
            json_data={
                "id": 300,
                "asset_id": 999,
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

        result = await sync_service.sync_maintenance_batch(
            maintenance_ids=[300],
            session_factory=mock_session_factory,
        )

        assert result["skipped"] == 1
        assert result["synced"] == 0
