"""
Integration tests for SnipeItSyncService.

Verifies that assets fetched from the Snipe-IT API are correctly
upserted into the `gear_items` table and their state is tracked
in `sync_metadata`.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from snipeit_api_client import SnipeItAPIClient
from snipeit_sync_service import SnipeItSyncService

# Using same mock transport pattern from other integration tests


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


class TestSnipeItSyncIntegration:
    @pytest.mark.asyncio
    async def test_sync_asset_batch_inserts_gear_item(
        self,
        sync_service: SnipeItSyncService,
        mock_transport: MockTransport,
        db_session: AsyncSession,
        async_engine: Any,
    ) -> None:
        """Verify that a successful asset sync upserts gear_items and sync_metadata."""

        # Setup API mock response
        asset_id = 999
        mock_transport.add_response(
            f"/hardware/{asset_id}",
            json_data={
                "id": asset_id,
                "name": "Climbing Rope 60m",
                "asset_tag": "ROPE-001",
                "serial": "SN-98765",
                "model_number": "MR-60",
                "model": {"id": 10, "name": "Dynamic 9.8mm"},
                "manufacturer": {"id": 5, "name": "Petzl"},
                "purchase_date": {"date": "2024-01-15", "formatted": "2024-01-15"},
                "category": {"id": 2, "name": "Climbing Gear"},
            },
        )

        # We need a session_factory for the sync service
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_session_factory():
            # Use the provided db_session which already has savepoints configured
            yield db_session

        # Run sync batch
        result = await sync_service.sync_asset_batch(
            asset_ids=[asset_id],
            session_factory=mock_session_factory,
        )

        assert result["synced"] == 1
        assert result["failed"] == 0

        # Verify gear_items row
        gear_result = await db_session.execute(
            text(
                "SELECT id, name, serial_number, manufacturer, purchase_date FROM gear_items WHERE user_id = 'user-123'"
            )
        )
        gear_row = gear_result.fetchone()
        assert gear_row is not None
        assert gear_row.name == "Climbing Rope 60m"
        assert gear_row.serial_number == "SN-98765"
        assert gear_row.manufacturer == "Petzl"
        assert str(gear_row.purchase_date) == "2024-01-15"

        gear_id = str(gear_row.id)

        # Verify sync_metadata row
        meta_result = await db_session.execute(
            text(
                "SELECT internal_uuid, version_hash, sync_status FROM sync_metadata WHERE integration_source = 'snipeit' AND external_id = '999'"
            )
        )
        meta_row = meta_result.fetchone()
        assert meta_row is not None
        assert meta_row.internal_uuid == gear_id
        assert meta_row.sync_status == "success"
        assert meta_row.version_hash is not None
