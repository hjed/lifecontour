"""
Integration tests for Snipe-IT stream consumer.

Verifies that a webhook stream event triggers the worker to process the asset
and update the database.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from core_shared.stream_client import StreamEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from snipeit_api_client import SnipeItAPIClient
from stream_consumer_tasks import SnipeItWorkerStreamConsumer


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


class TestStreamConsumerIntegration:
    @pytest.mark.asyncio
    async def test_webhook_event_processes_asset(
        self,
        db_session: AsyncSession,
        async_connection: Any,
        mock_transport: MockTransport,
    ) -> None:
        """A webhook event upserts the asset for its owner and no other user."""

        # 1. Setup DB state: two users with Snipe-IT auth and settings
        user_id = "test-user-for-webhook"
        other_user_id = "other-user-for-webhook"
        snipeit_user_id = "123"

        for configured_user_id in (user_id, other_user_id):
            await async_connection.execute(
                text("""
                    INSERT INTO user_snipe_it_auth (
                        user_id, encrypted_api_key,
                        created_at, updated_at
                    ) VALUES (
                        :user_id, 'enc-api-key',
                        now(), now()
                    )
                """),
                {"user_id": configured_user_id},
            )
            await async_connection.execute(
                text("""
                    INSERT INTO snipeit_settings (
                        user_id, base_url, snipeit_user_id, webhook_token, created_at, updated_at
                    ) VALUES (
                        :user_id, 'https://snipeit.example.com', :snipeit_user_id,
                        :webhook_token, now(), now()
                    )
                """),
                {
                    "user_id": configured_user_id,
                    "snipeit_user_id": snipeit_user_id,
                    "webhook_token": f"webhook-token-{configured_user_id}",
                },
            )
        # 2. Setup mock API response
        asset_id = 142
        mock_transport.add_response(
            f"/hardware/{asset_id}",
            json_data={
                "id": asset_id,
                "name": "Webhook Rope",
                "asset_tag": "ROPE-WH-001",
                "serial": "SN-WH-999",
                "assigned_to": {"id": snipeit_user_id, "type": "user"},
            },
        )

        # We need a session_factory to pass to the consumer
        from contextlib import asynccontextmanager

        from sqlalchemy.ext.asyncio import AsyncSession as SqlAsyncSession

        @asynccontextmanager
        async def mock_session_factory():
            async with SqlAsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        mock_stream_client = AsyncMock()
        consumer = SnipeItWorkerStreamConsumer(
            stream_client=mock_stream_client,
            session_factory=mock_session_factory,
        )

        # 3. Create the event
        event = StreamEvent(
            message_id="123",
            event_id="abc",
            event_type="snipeit.webhook_received",
            aggregate_id=0,
            event_data={
                "action": "hardware_created",
                "item": {"id": asset_id},
                "user_id": user_id,
            },
            occurred_at="2024-01-01T00:00:00Z",
        )

        # 4. Process event with mocked get_auth_data / API client
        # worker uses fernet which requires a valid token, so we mock _get_auth_data or just mock _create_sync_service
        # But wait, it's better to just mock `_create_sync_service` to return an API client that uses our mock_transport

        def mock_create_service(
            user_id: str,
            auth_data: dict[str, Any],
            base_url: str,
            snipeit_user_id: str | None,
            worker_settings: Any,
            session_factory: Any,
        ) -> Any:
            from snipeit_sync_service import SnipeItSyncService

            client = SnipeItAPIClient.create(
                base_url=base_url,
                api_key="test",
            )
            client._client = httpx.AsyncClient(
                transport=mock_transport,
                base_url=f"{base_url.rstrip('/')}/api/v1/",
            )
            return SnipeItSyncService(
                api_client=client,
                user_id=user_id,
                snipeit_user_id=snipeit_user_id,
            )

        with patch("worker._create_sync_service", side_effect=mock_create_service):
            # We also need to mock _get_auth_data since it's called
            with patch(
                "worker._get_auth_data", return_value={"mock": "data"}
            ) as mock_get_auth_data:
                await consumer._handle_event(event)

        # Only the webhook's owner is synced
        mock_get_auth_data.assert_called_once_with(mock_session_factory, user_id)

        # 5. Verify the gear item was inserted
        gear_result = await db_session.execute(
            text(
                "SELECT id, name, serial_number FROM gear_items WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
        gear_row = gear_result.fetchone()
        assert gear_row is not None
        assert gear_row.name == "Webhook Rope"
        assert gear_row.serial_number == "SN-WH-999"
        other_gear = await db_session.execute(
            text("SELECT id FROM gear_items WHERE user_id = :user_id"),
            {"user_id": other_user_id},
        )
        assert other_gear.fetchall() == []

    @pytest.mark.asyncio
    async def test_gear_item_updated_event_pushes_to_snipeit(
        self,
        db_session: AsyncSession,
        async_connection: Any,
        mock_transport: MockTransport,
    ) -> None:
        """Verify that receiving a GearItemUpdated event triggers push to Snipe-IT."""
        user_id = "test-user-for-export"
        snipeit_user_id = "123"
        gear_item_uuid = "00000000-0000-0000-0000-000000000001"
        asset_id = 456

        await async_connection.execute(
            text("""
                INSERT INTO user_snipe_it_auth (user_id, encrypted_api_key, created_at, updated_at)
                VALUES (:user_id, 'enc-api-key', now(), now())
            """),
            {"user_id": user_id},
        )
        await async_connection.execute(
            text("""
                INSERT INTO snipeit_settings (user_id, base_url, snipeit_user_id, webhook_token, created_at, updated_at)
                VALUES (:user_id, 'https://snipeit.example.com', :snipeit_user_id, :webhook_token, now(), now())
            """),
            {
                "user_id": user_id,
                "snipeit_user_id": snipeit_user_id,
                "webhook_token": f"webhook-token-{user_id}",
            },
        )
        await async_connection.execute(
            text("""
                INSERT INTO gear_items (id, user_id, name, serial_number, created_at, updated_at)
                VALUES (:id, :user_id, 'Old Name', 'Old Serial', now(), now())
            """),
            {"id": gear_item_uuid, "user_id": user_id},
        )

        # Insert sync metadata with a version hash
        # To simulate a match, we need to know the version hash of the mocked GET response.
        # We will define the mock response, hash it, and insert it.
        from snipeit_data_transformer import SnipeItDataTransformer
        from snipeit_models import SnipeItAsset

        asset_json = {
            "id": asset_id,
            "name": "Old Name",
            "asset_tag": "TAG-123",
            "serial": "Old Serial",
            "assigned_to": {"id": int(snipeit_user_id), "type": "user"},
        }

        asset = SnipeItAsset.model_validate(asset_json)
        version_hash = (
            SnipeItDataTransformer().transform(asset, user_id=user_id).version_hash
        )

        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata (internal_uuid, integration_source, external_id, last_synced_at, version_hash, sync_status, retry_count, created_at, updated_at)
                VALUES (:id, 'snipeit', :external_id, now(), :version_hash, 'success', 0, now(), now())
            """),
            {
                "id": gear_item_uuid,
                "external_id": str(asset_id),
                "version_hash": version_hash,
            },
        )

        # Mock GET response (used for conflict check)
        mock_transport.add_response(f"/hardware/{asset_id}", json_data=asset_json)

        # Mock PATCH response
        updated_asset_json = {**asset_json, "name": "New Name", "serial": "New Serial"}
        mock_transport.add_response(
            f"/hardware/{asset_id}",
            status_code=200,
            json_data={"status": "success", "payload": updated_asset_json},
        )

        from contextlib import asynccontextmanager

        from sqlalchemy.ext.asyncio import AsyncSession as SqlAsyncSession

        @asynccontextmanager
        async def mock_session_factory():
            async with SqlAsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        mock_stream_client = AsyncMock()
        consumer = SnipeItWorkerStreamConsumer(
            stream_client=mock_stream_client,
            session_factory=mock_session_factory,
        )

        event = StreamEvent(
            message_id="123",
            event_id="abc",
            event_type="GearItemUpdated",
            aggregate_id=0,
            event_data={
                "gear_item_id": gear_item_uuid,
                "changed_fields": {
                    "name": ["Old Name", "New Name"],
                    "serial_number": ["Old Serial", "New Serial"],
                },
            },
            occurred_at="2024-01-01T00:00:00Z",
        )

        def mock_create_service(
            user_id: str,
            auth_data: dict[str, Any],
            base_url: str,
            snipeit_user_id: str | None,
            worker_settings: Any,
            session_factory: Any,
            **kwargs: Any,
        ) -> Any:
            from snipeit_sync_service import SnipeItSyncService

            client = SnipeItAPIClient.create(base_url=base_url, api_key="test")
            client._client = httpx.AsyncClient(
                transport=mock_transport, base_url=f"{base_url.rstrip('/')}/api/v1/"
            )
            return SnipeItSyncService(
                api_client=client, user_id=user_id, snipeit_user_id=snipeit_user_id
            )

        with patch("worker._create_sync_service", side_effect=mock_create_service):
            with patch(
                "worker._get_auth_data", return_value={"mock": "data"}
            ) as mock_get_auth_data:
                await consumer._handle_event(event)

        # Only the webhook's owner is synced
        mock_get_auth_data.assert_called_once_with(mock_session_factory, user_id)

        # Verify sync metadata was updated with the new version hash
        meta_result = await db_session.execute(
            text("SELECT version_hash FROM sync_metadata WHERE internal_uuid = :id"),
            {"id": gear_item_uuid},
        )
        meta_row = meta_result.fetchone()
        assert meta_row is not None
        assert (
            meta_row.version_hash != version_hash
        )  # Hash should be updated to the new one
