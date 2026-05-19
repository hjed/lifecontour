"""
Unit tests for Snipe-IT worker stream consumer tasks.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamEvent

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/test"
    )
if "ENCRYPTION_KEY" not in os.environ:
    os.environ["ENCRYPTION_KEY"] = "testkey"

from stream_consumer_tasks import SnipeItWorkerStreamConsumer


@pytest.fixture
def mock_stream_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_session_factory() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_handle_event_skips_non_webhook_event(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """Non-webhook events are skipped."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="other.event",
        aggregate_id=0,
        event_data={},
        occurred_at="2024-01-01T00:00:00Z",
    )

    with patch("worker._get_auth_data") as mock_get_auth_data:
        await consumer._handle_event(event)
        mock_get_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_skips_invalid_payload(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """Missing or invalid item payloads are skipped."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="snipeit.webhook_received",
        aggregate_id=0,
        event_data={"action": "hardware_created"},  # No item
        occurred_at="2024-01-01T00:00:00Z",
    )

    with patch("worker._get_auth_data") as mock_get_auth_data:
        await consumer._handle_event(event)
        mock_get_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_processes_asset(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """Valid webhook processes the asset for configured users."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="snipeit.webhook_received",
        aggregate_id=0,
        event_data={"action": "hardware_created", "item": {"id": 42}},
        occurred_at="2024-01-01T00:00:00Z",
    )

    # Mock database session returning one user with Snipe-IT configured
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        MagicMock(user_id="user1", base_url="http://snipeit", snipeit_user_id="s1")
    ]
    mock_session.execute.return_value = mock_result

    # Mock sync service creation and execution
    mock_sync_service = AsyncMock()
    mock_sync_service._sync_single_asset_with_retry = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}) as mock_get_auth,
        patch(
            "worker._create_sync_service", return_value=mock_sync_service
        ) as mock_create_service,
    ):
        await consumer._handle_event(event)

        mock_get_auth.assert_called_once_with(mock_session_factory, "user1")
        mock_create_service.assert_called_once()

        # Verify it tries to sync asset 42
        mock_sync_service._sync_single_asset_with_retry.assert_called_once_with(
            asset_id=42,
            session_factory=mock_session_factory,
        )
        # Verify it cleans up the api client
        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_event_processes_gear_item_updated(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """Valid GearItemUpdated processes the export to Snipe-IT."""
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
            "gear_item_id": "uuid-123",
            "changed_fields": {"name": ("old", "new")},
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    # Mock database session returning one user with Snipe-IT configured
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_result = MagicMock()
    mock_result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    mock_session.execute.return_value = mock_result

    # Mock sync service creation and execution
    mock_sync_service = AsyncMock()
    mock_sync_service.push_asset_update = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}) as mock_get_auth,
        patch(
            "worker._create_sync_service", return_value=mock_sync_service
        ) as mock_create_service,
    ):
        await consumer._handle_event(event)

        mock_get_auth.assert_called_once_with(mock_session_factory, "user1")
        mock_create_service.assert_called_once()

        mock_sync_service.push_asset_update.assert_called_once_with(
            gear_item_id="uuid-123",
            changed_fields={"name": ("old", "new")},
            session_factory=mock_session_factory,
        )
        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_event_processes_maintenance_webhook(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """Maintenance webhook events are routed to the maintenance handler."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="snipeit.webhook_received",
        aggregate_id=0,
        event_data={
            "action": "maintenance_created",
            "item": {"id": 77, "title": "Rope Inspection"},
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    # Mock database session returning one user with Snipe-IT configured
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        MagicMock(user_id="user1", base_url="http://snipeit", snipeit_user_id="s1")
    ]
    mock_session.execute.return_value = mock_result

    # Mock sync service
    mock_sync_service = AsyncMock()
    mock_sync_service.sync_maintenance_batch = AsyncMock(
        return_value={"synced": 1, "skipped": 0, "failed": 0}
    )
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}) as mock_get_auth,
        patch(
            "worker._create_sync_service", return_value=mock_sync_service
        ) as mock_create_service,
    ):
        await consumer._handle_event(event)

        mock_get_auth.assert_called_once_with(mock_session_factory, "user1")
        mock_create_service.assert_called_once()

        # Verify it syncs maintenance ID 77
        mock_sync_service.sync_maintenance_batch.assert_called_once_with(
            maintenance_ids=[77],
            session_factory=mock_session_factory,
        )
        mock_sync_service._api_client.close.assert_called_once()
