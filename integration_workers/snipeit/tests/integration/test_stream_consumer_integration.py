"""
Integration tests for Snipe-IT stream consumer.

Verifies that a webhook stream event triggers the worker to process the asset
and update the database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from core_shared.stream_client import StreamEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from snipeit_api_client import SnipeItAPIClient
from stream_consumer_tasks import SnipeItWorkerStreamConsumer

from .test_maintenance_sync_integration import _import_rows, _listed

# ``mock_transport`` is the shared fixture defined in ``conftest.py``.


async def _configure_snipeit(
    async_connection: Any, user_id: str, snipeit_user_id: str
) -> None:
    """Give ``user_id`` Snipe-IT auth and settings."""
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
        {"user_id": user_id},
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
            "user_id": user_id,
            "snipeit_user_id": snipeit_user_id,
            "webhook_token": f"webhook-token-{user_id}",
        },
    )


def _joined_session_factory(async_connection: Any) -> Any:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    return session_factory


def _sync_service_on(mock_transport: Any) -> Callable[..., Any]:
    """A ``_create_sync_service`` stand-in whose client calls ``mock_transport``.

    The real one decrypts the API key, which needs a valid Fernet token.
    """

    def create_sync_service(
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

    return create_sync_service


def _webhook_event(asset_id: int, user_id: str) -> StreamEvent:
    return StreamEvent(
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


async def _handle(
    consumer: SnipeItWorkerStreamConsumer, event: StreamEvent, mock_transport: Any
) -> AsyncMock:
    """Handle ``event`` against ``mock_transport``; return the auth lookup mock."""
    with (
        patch(
            "worker._create_sync_service", side_effect=_sync_service_on(mock_transport)
        ),
        patch("worker._get_auth_data", return_value={"mock": "data"}) as get_auth_data,
    ):
        await consumer._handle_event(event)
    return get_auth_data


class TestStreamConsumerIntegration:
    @pytest.mark.asyncio
    async def test_webhook_event_processes_asset(
        self,
        db_session: AsyncSession,
        async_connection: Any,
        mock_transport: Any,
    ) -> None:
        """A webhook event upserts the asset for its owner and no other user."""
        user_id = "test-user-for-webhook"
        other_user_id = "other-user-for-webhook"
        snipeit_user_id = "123"
        for configured_user_id in (user_id, other_user_id):
            await _configure_snipeit(
                async_connection, configured_user_id, snipeit_user_id
            )
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
        session_factory = _joined_session_factory(async_connection)
        consumer = SnipeItWorkerStreamConsumer(
            stream_client=AsyncMock(), session_factory=session_factory
        )

        get_auth_data = await _handle(
            consumer, _webhook_event(asset_id, user_id), mock_transport
        )

        # Only the webhook's owner is synced
        get_auth_data.assert_called_once_with(session_factory, user_id)
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
    async def test_webhook_linking_a_new_asset_imports_its_maintenances(
        self,
        async_connection: Any,
        mock_transport: Any,
    ) -> None:
        """A record skipped while its asset was unlinked arrives with the asset (#1563)."""
        user_id = "user-123"
        await _configure_snipeit(async_connection, user_id, "5")
        mock_transport.add_response(
            "/hardware/51",
            json_data={"id": 51, "name": "Canyoneroo 50m", "asset_tag": "00051"},
            method="GET",
        )
        mock_transport.add_response(
            "asset_id=51", json_data={"total": 1, "rows": [_listed(301)]}, method="GET"
        )
        mock_transport.add_response(
            "/maintenances/301", json_data=_listed(301), method="GET"
        )
        consumer = SnipeItWorkerStreamConsumer(
            stream_client=AsyncMock(),
            session_factory=_joined_session_factory(async_connection),
        )

        await _handle(consumer, _webhook_event(51, user_id), mock_transport)

        assert await _import_rows(async_connection, 301) == 1

    @pytest.mark.asyncio
    async def test_gear_item_updated_event_pushes_to_snipeit(
        self,
        db_session: AsyncSession,
        async_connection: Any,
        mock_transport: Any,
    ) -> None:
        """Verify that receiving a GearItemUpdated event triggers push to Snipe-IT."""
        user_id = "test-user-for-export"
        snipeit_user_id = "123"
        gear_item_uuid = "00000000-0000-0000-0000-000000000001"
        asset_id = 456

        await _configure_snipeit(async_connection, user_id, snipeit_user_id)
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
                INSERT INTO sync_metadata (user_id, internal_uuid, integration_source, external_id, last_synced_at, version_hash, sync_status, retry_count, created_at, updated_at)
                VALUES (:user_id, :id, 'snipeit', :external_id, now(), :version_hash, 'success', 0, now(), now())
            """),
            {
                "user_id": user_id,
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

        mock_session_factory = _joined_session_factory(async_connection)

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

        mock_get_auth_data = await _handle(consumer, event, mock_transport)

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

    @pytest.mark.asyncio
    async def test_journal_deleted_clears_a_claim_without_snipeit_settings(
        self,
        async_connection: Any,
    ) -> None:
        """A claim-only deletion is cleared against a real session.

        The unit test for this path mocks ``session.begin()``, which hides
        whether the handler's transaction handling is valid on a real
        ``AsyncSession`` that the fast-path query has already opened one on.
        """
        from contextlib import asynccontextmanager

        from sqlalchemy.ext.asyncio import AsyncSession as SqlAsyncSession

        user_id = "user-with-a-deleted-maintenance-journal"
        journal_id = 987654
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (user_id, internal_uuid, integration_source, external_id,
                     last_synced_at, version_hash, sync_status, retry_count,
                     reference_data, created_at, updated_at)
                VALUES
                    (:user_id, :journal_id, 'snipeit_maintenance_claim', :journal_id,
                     now(), 'PENDING', 'failed', 0,
                     '{"asset_id": 51, "title": "Retire Harness",
                       "start_date": "2026-09-11"}', now(), now())
            """),
            {"user_id": user_id, "journal_id": str(journal_id)},
        )

        @asynccontextmanager
        async def session_factory() -> AsyncIterator[SqlAsyncSession]:
            async with SqlAsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        consumer = SnipeItWorkerStreamConsumer(
            stream_client=AsyncMock(),
            session_factory=session_factory,
        )
        event = StreamEvent(
            message_id="123",
            event_id="abc",
            event_type="JournalDeleted",
            aggregate_id=journal_id,
            event_data={"journal_id": journal_id, "user_id": user_id},
            occurred_at="2026-09-20T00:00:00Z",
        )

        # No snipeit_settings row for this user: clearing a claim is a database
        # write and must not wait on credentials.
        with (
            patch("worker._get_auth_data") as mock_get_auth,
            patch("worker._create_sync_service") as mock_create,
        ):
            await consumer._handle_event(event)

        mock_get_auth.assert_not_called()
        mock_create.assert_not_called()
        remaining = await async_connection.execute(
            text("""
                SELECT 1 FROM sync_metadata
                WHERE integration_source = 'snipeit_maintenance_claim'
                  AND external_id = :journal_id
            """),
            {"journal_id": str(journal_id)},
        )
        assert remaining.fetchone() is None

    @pytest.mark.asyncio
    async def test_a_journal_that_lost_its_gear_is_still_reconciled(
        self,
        async_connection: Any,
    ) -> None:
        """Only its checkout rows are left once every gear item is removed.

        The update must still reach the reconcile, which returns the assets.
        """
        from contextlib import asynccontextmanager

        from sqlalchemy.ext.asyncio import AsyncSession as SqlAsyncSession

        user_id = "user-whose-trip-lost-its-gear"
        await async_connection.execute(
            text("""
                INSERT INTO snipeit_settings
                    (user_id, base_url, snipeit_user_id, webhook_token,
                     created_at, updated_at)
                VALUES (:user_id, 'https://snipeit.example.com', 5, 'token-1574',
                        now(), now())
            """),
            {"user_id": user_id},
        )
        journal_id = (
            await async_connection.execute(
                text("""
                    INSERT INTO journals (title, content, user_id,
                        event_date_range_start, event_date_range_end)
                    VALUES ('Trip', '', :user_id, now(), now())
                    RETURNING id
                """),
                {"user_id": user_id},
            )
        ).scalar()
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (user_id, internal_uuid, integration_source, external_id,
                     last_synced_at, version_hash, sync_status, retry_count,
                     created_at, updated_at)
                VALUES
                    ('user-123', :journal_uuid, 'snipeit_checkout', :external_id,
                     now(), 'hash', 'success', 0, now(), now())
            """),
            {
                "journal_uuid": str(journal_id),
                "external_id": f"snipeit_checkout:42:{journal_id}",
            },
        )

        @asynccontextmanager
        async def session_factory() -> AsyncIterator[SqlAsyncSession]:
            async with SqlAsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        consumer = SnipeItWorkerStreamConsumer(
            stream_client=AsyncMock(),
            session_factory=session_factory,
        )
        event = StreamEvent(
            message_id="124",
            event_id="def",
            event_type="JournalUpdated",
            aggregate_id=journal_id,
            event_data={"journal_id": journal_id, "changed_fields": {}},
            occurred_at="2026-09-26T00:00:00Z",
        )
        sync_service = AsyncMock()

        with (
            patch("worker._get_auth_data", return_value={"mock": "auth"}),
            patch("worker._create_sync_service", return_value=sync_service),
        ):
            await consumer._handle_event(event)

        sync_service.reconcile_gear_usage.assert_awaited_once()
        assert (
            sync_service.reconcile_gear_usage.await_args.kwargs["journal_id"]
            == journal_id
        )
