"""
Unit tests for Snipe-IT worker stream consumer tasks.
"""

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamEvent

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/test"
    )
if "ENCRYPTION_KEY" not in os.environ:
    os.environ["ENCRYPTION_KEY"] = "testkey"

from snipeit_sync_service import GearUsagePair
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
async def test_webhook_without_user_is_skipped(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """A webhook event without an owner syncs nobody rather than every user."""
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

    with patch("worker._get_auth_data") as mock_get_auth_data:
        await consumer._handle_event(event)

    mock_session_factory.assert_not_called()
    mock_get_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_for_user_without_settings_is_skipped(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """An owner whose Snipe-IT settings have since been removed is not synced."""
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
            "action": "hardware_created",
            "item": {"id": 42},
            "user_id": "user1",
        },
        occurred_at="2024-01-01T00:00:00Z",
    )
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute.return_value = mock_result

    with patch("worker._get_auth_data") as mock_get_auth_data:
        await consumer._handle_event(event)

    mock_get_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_processes_asset(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """A valid webhook syncs the asset for the webhook's owner only."""
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
            "action": "hardware_created",
            "item": {"id": 42},
            "user_id": "user1",
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
    mock_sync_service._sync_single_asset_with_retry = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}) as mock_get_auth,
        patch(
            "worker._create_sync_service", return_value=mock_sync_service
        ) as mock_create_service,
    ):
        await consumer._handle_event(event)

        query_params = mock_session.execute.call_args.args[1]
        assert query_params == {"user_id": "user1"}
        mock_get_auth.assert_called_once_with(mock_session_factory, "user1")
        mock_create_service.assert_called_once()
        assert mock_create_service.call_args.kwargs["user_id"] == "user1"

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
async def test_handle_event_syncs_asset_when_action_mentions_maintenance(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """Webhook item ids are always assets, whatever the notification text says.

    The action is Snipe-IT's free-text Slack message, and Snipe-IT never sends
    maintenance notifications, so a mention of maintenance must not turn the
    asset id into a maintenance id.
    """
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
            "action": "Asset Checkin Notification: returned after maintenance",
            "item": {"id": 77},
            "user_id": "user1",
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

    # Mock sync service
    mock_sync_service = AsyncMock()
    mock_sync_service._sync_single_asset_with_retry = AsyncMock()
    mock_sync_service.sync_maintenance_batch = AsyncMock(
        return_value={"synced": 1, "skipped": 0, "failed": 0}
    )
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(event)

        mock_sync_service._sync_single_asset_with_retry.assert_called_once_with(
            asset_id=77,
            session_factory=mock_session_factory,
        )
        mock_sync_service.sync_maintenance_batch.assert_not_called()
        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_event_processes_journal_created_gear_maintenance(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalCreated event for GEAR_MAINTENANCE triggers push_maintenance_create."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalCreated",
        aggregate_id=100,
        event_data={
            "journal_id": 100,
            "user_id": "user1",
            "title": "Rope Inspection",
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    # Mock DB: user has Snipe-IT settings, journal has GEAR_MAINTENANCE type
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    # First query: snipeit_settings (user lookup)
    settings_result = MagicMock()
    settings_result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    # Second query: journal_gear_maintenance_data check
    maintenance_check = MagicMock()
    maintenance_check.fetchone.return_value = MagicMock(journal_id=100)

    mock_session.execute = AsyncMock(side_effect=[settings_result, maintenance_check])

    mock_sync_service = AsyncMock()
    mock_sync_service.push_maintenance_create = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(event)

        mock_sync_service.push_maintenance_create.assert_called_once_with(
            journal_id=100,
            session_factory=mock_session_factory,
        )
        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_event_skips_journal_created_non_maintenance(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalCreated event for non-GEAR_MAINTENANCE journal is skipped."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalCreated",
        aggregate_id=100,
        event_data={
            "journal_id": 100,
            "user_id": "user1",
            "title": "Regular Note",
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    # Mock DB: user has Snipe-IT settings, but journal has no GEAR_MAINTENANCE or GEAR_USAGE data
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    settings_result = MagicMock()
    settings_result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    maintenance_check = MagicMock()
    maintenance_check.fetchone.return_value = None  # No maintenance data
    usage_check = MagicMock()
    usage_check.fetchone.return_value = None  # No usage data either

    mock_session.execute = AsyncMock(
        side_effect=[settings_result, maintenance_check, usage_check]
    )

    mock_get_auth = AsyncMock(return_value={"mock": "auth"})

    with (
        patch("worker._get_auth_data", mock_get_auth),
        patch("worker._create_sync_service") as mock_create,
    ):
        await consumer._handle_event(event)

        # Should NOT attempt auth or create sync service for non-maintenance/non-usage
        mock_get_auth.assert_not_called()
        mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_processes_journal_updated_gear_maintenance(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalUpdated event for GEAR_MAINTENANCE triggers push_maintenance_update."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalUpdated",
        aggregate_id=100,
        event_data={
            "journal_id": 100,
            "changed_fields": {"title": ["Old", "New"]},
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    settings_result = MagicMock()
    settings_result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    maintenance_check = MagicMock()
    maintenance_check.fetchone.return_value = MagicMock(journal_id=100)

    mock_session.execute = AsyncMock(side_effect=[settings_result, maintenance_check])

    mock_sync_service = AsyncMock()
    mock_sync_service.push_maintenance_update = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(event)

        mock_sync_service.push_maintenance_update.assert_called_once_with(
            journal_id=100,
            session_factory=mock_session_factory,
        )
        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_event_skips_journal_updated_applied_by_inbound_maintenance_sync(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """An update the Snipe-IT import applied is already Snipe-IT's state; pushing
    it back would echo the record to where it came from."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalUpdated",
        aggregate_id=100,
        event_data={
            "journal_id": 100,
            "changed_fields": {"title": ["Old", "New"]},
            "source": "system",
            "changed_by": "snipeit_maintenance",
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    with patch("worker._create_sync_service") as mock_create_sync_service:
        await consumer._handle_event(event)

        mock_session_factory.assert_not_called()
        mock_create_sync_service.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_processes_journal_created_gear_usage(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalCreated event for GEAR_USAGE triggers push_checkout_create."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalCreated",
        aggregate_id=100,
        event_data={
            "journal_id": 100,
            "user_id": "user1",
            "title": "Gear Usage Log",
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    # Mock DB: user has Snipe-IT settings
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    settings_result = MagicMock()
    settings_result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    # First query: snipeit_settings; second: maintenance check (None);
    # third: usage check (found)
    maintenance_check = MagicMock()
    maintenance_check.fetchone.return_value = None  # No maintenance data
    usage_check = MagicMock()
    usage_check.fetchone.return_value = MagicMock(journal_id=100)

    mock_session.execute = AsyncMock(
        side_effect=[settings_result, maintenance_check, usage_check]
    )

    mock_sync_service = AsyncMock()
    mock_sync_service.push_checkout_create = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(event)

        mock_sync_service.push_checkout_create.assert_called_once_with(
            journal_id=100,
            session_factory=mock_session_factory,
        )
        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_event_skips_journal_created_no_maintenance_no_usage(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalCreated event with neither maintenance nor usage data is skipped."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalCreated",
        aggregate_id=100,
        event_data={
            "journal_id": 100,
            "user_id": "user1",
            "title": "Regular Note",
        },
        occurred_at="2024-01-01T00:00:00Z",
    )

    # Mock DB: user has Snipe-IT settings, but journal has no maintenance OR usage data
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    settings_result = MagicMock()
    settings_result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    maintenance_check = MagicMock()
    maintenance_check.fetchone.return_value = None  # No maintenance data
    usage_check = MagicMock()
    usage_check.fetchone.return_value = None  # No usage data either

    mock_session.execute = AsyncMock(
        side_effect=[settings_result, maintenance_check, usage_check]
    )

    mock_get_auth = AsyncMock(return_value={"mock": "auth"})

    with (
        patch("worker._get_auth_data", mock_get_auth),
        patch("worker._create_sync_service") as mock_create,
    ):
        await consumer._handle_event(event)

        # Should NOT attempt auth or create sync service for non-maintenance/non-usage
        mock_get_auth.assert_not_called()
        mock_create.assert_not_called()


def _gear_usage_updated_event(mock_session_factory: MagicMock) -> StreamEvent:
    """A GEAR_USAGE ``JournalUpdated`` event, with the lookups it triggers mocked."""
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    settings_result = MagicMock()
    settings_result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    maintenance_check = MagicMock()
    maintenance_check.fetchone.return_value = None  # not a maintenance journal
    usage_check = MagicMock()
    usage_check.fetchone.return_value = MagicMock()  # has gear usage data

    mock_session.execute = AsyncMock(
        side_effect=[settings_result, maintenance_check, usage_check]
    )
    return StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalUpdated",
        aggregate_id=100,
        event_data={
            "journal_id": 100,
            "user_id": "user1",
            "title": "Gear Usage Note",
            "journal_type": "GEAR_USAGE",
        },
        occurred_at="2024-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_handle_event_journal_updated_gear_usage_reconciles(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalUpdated events for GEAR_USAGE reconcile checkout/checkin state."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = _gear_usage_updated_event(mock_session_factory)

    mock_sync_service = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(event)

    mock_sync_service.reconcile_gear_usage.assert_called_once_with(
        journal_id=100,
        session_factory=mock_session_factory,
    )
    mock_sync_service.push_checkout_create.assert_not_called()
    mock_sync_service._api_client.close.assert_called_once()


def _sync_rows(*integration_sources: str) -> MagicMock:
    """The sync rows naming a deleted journal, as the handler's fast path reads them."""
    result = MagicMock()
    result.fetchall.return_value = [
        MagicMock(integration_source=source) for source in integration_sources
    ]
    return result


def _settings_row() -> MagicMock:
    """The journal owner's Snipe-IT settings."""
    result = MagicMock()
    result.fetchone.return_value = MagicMock(
        user_id="user1", base_url="http://snipeit", snipeit_user_id="s1"
    )
    return result


def _journal_deleted_event(*imported: str) -> StreamEvent:
    """A ``JournalDeleted`` for journal 100, which carries no journal type.

    ``imported`` are the Snipe-IT records the journal was imported from, as
    the event carries them: an import's sync row names no journal, so its
    external id reaches the worker only here.
    """
    event_data: dict[str, Any] = {"journal_id": 100, "user_id": "user1"}
    if imported:
        event_data["external_identifiers"] = {
            "snipeit_maintenance": [
                {
                    "external_event_id": external_id,
                    "calendar_id": "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a",
                    "google_calendar_id": None,
                }
                for external_id in imported
            ]
        }
    return StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalDeleted",
        aggregate_id=100,
        event_data=event_data,
        occurred_at="2024-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_handle_journal_deleted_deletes_an_imported_record(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """An imported journal's record is reached through the event, not a sync row.

    Its row names no journal, so the handler's "did this journal put anything
    in Snipe-IT?" query finds nothing and used to return before doing anything.
    """
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(side_effect=[_sync_rows(), _settings_row()])

    mock_sync_service = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(_journal_deleted_event("snipeit_maint:17"))

    mock_sync_service.delete_maintenance_record.assert_called_once()
    call = mock_sync_service.delete_maintenance_record.call_args
    assert call.kwargs["external_id"] == "snipeit_maint:17"
    mock_sync_service.delete_pushed_maintenance.assert_not_called()
    mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_journal_deleted_takes_credentials_for_an_import_with_a_claim(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """A claim beside an imported record must not take the credential-free path.

    Clearing a lone claim is a database write and deliberately skips the
    credential lookup. Deleting a record is not: routing this journal that way
    would leave its record in Snipe-IT to import again as a new journal.
    """
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(
        side_effect=[_sync_rows("snipeit_maintenance_claim"), _settings_row()]
    )

    mock_sync_service = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}) as mock_get_auth,
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(_journal_deleted_event("snipeit_maint:17"))

    mock_get_auth.assert_called_once()
    mock_sync_service.delete_maintenance_record.assert_called_once()
    # The claim goes with the record, as it does for a pushed journal.
    mock_sync_service.delete_pushed_maintenance.assert_called_once()


@pytest.mark.asyncio
async def test_handle_journal_deleted_deletes_the_pushed_maintenance(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """A journal with a maintenance push row has its Snipe-IT record deleted."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session.execute = AsyncMock(
        side_effect=[_sync_rows("snipeit_maintenance"), _settings_row()]
    )

    mock_sync_service = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(_journal_deleted_event())

    mock_sync_service.delete_pushed_maintenance.assert_called_once()
    call = mock_sync_service.delete_pushed_maintenance.call_args
    assert call.kwargs["journal_id"] == 100
    mock_sync_service.push_checkin_create.assert_not_called()
    mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_journal_deleted_clears_a_leftover_claim(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """A claim is all a push that failed before recording leaves, and it must go.

    Clearing it is a database write, so it must not wait on Snipe-IT
    credentials: a user who disconnected the integration would otherwise leave
    the claim behind for good.
    """
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=transaction)
    mock_session.execute = AsyncMock(
        side_effect=[_sync_rows("snipeit_maintenance_claim"), MagicMock()]
    )

    with (
        patch("worker._get_auth_data") as mock_get_auth,
        patch("worker._create_sync_service") as mock_create,
    ):
        await consumer._handle_event(_journal_deleted_event())

    # The claim is deleted directly; nothing here needs a Snipe-IT call.
    deletes = [
        call
        for call in mock_session.execute.call_args_list
        if "DELETE FROM sync_metadata" in str(call.args[0])
    ]
    assert len(deletes) == 1
    mock_get_auth.assert_not_called()
    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_handle_journal_deleted_checks_in_asset(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalDeleted checks in every (journal, asset) pair the journal held."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalDeleted",
        aggregate_id=100,
        event_data={"journal_id": 100, "user_id": "user1"},
        occurred_at="2024-01-01T00:00:00Z",
    )

    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    checkout_rows = MagicMock()
    checkout_rows.__iter__.return_value = [
        MagicMock(external_id="snipeit_checkout:42:100"),
        MagicMock(external_id="snipeit_checkout:43:100"),
    ]
    mock_session.execute = AsyncMock(
        side_effect=[_sync_rows("snipeit_checkout"), _settings_row(), checkout_rows]
    )

    mock_sync_service = AsyncMock()
    mock_sync_service._api_client = AsyncMock()

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
    ):
        await consumer._handle_event(event)

    assert [
        call.args[0] for call in mock_sync_service.push_checkin_create.await_args_list
    ] == [GearUsagePair(100, 42), GearUsagePair(100, 43)]
    mock_sync_service.delete_pushed_maintenance.assert_not_called()
    mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_journal_deleted_skips_without_any_sync_row(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """JournalDeleted for a journal Snipe-IT never recorded is a no-op."""
    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = StreamEvent(
        message_id="123",
        event_id="abc",
        event_type="JournalDeleted",
        aggregate_id=100,
        event_data={"journal_id": 100, "user_id": "user1"},
        occurred_at="2024-01-01T00:00:00Z",
    )

    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    mock_session.execute = AsyncMock(side_effect=[_sync_rows()])

    with (
        patch("worker._get_auth_data") as mock_get_auth,
        patch("worker._create_sync_service") as mock_create,
    ):
        await consumer._handle_event(event)

        mock_get_auth.assert_not_called()
        mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_gear_usage_in_flight_checkout_is_left_for_retry(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """An in-flight checkout propagates, leaving the stream event pending to retry."""
    from snipeit_sync_service import SnipeItSyncInProgress

    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )
    event = _gear_usage_updated_event(mock_session_factory)
    mock_sync_service = AsyncMock()
    mock_sync_service._api_client = AsyncMock()
    mock_sync_service.reconcile_gear_usage.side_effect = SnipeItSyncInProgress(
        "checkout in flight"
    )

    with (
        patch("worker._get_auth_data", return_value={"mock": "auth"}),
        patch("worker._create_sync_service", return_value=mock_sync_service),
        pytest.raises(SnipeItSyncInProgress),
    ):
        await consumer._handle_event(event)

    mock_sync_service._api_client.close.assert_called_once()


def test_retry_budget_outlasts_an_abandoned_snipeit_lock(
    mock_stream_client: AsyncMock,
    mock_session_factory: MagicMock,
) -> None:
    """A dead worker's Snipe-IT lock must go stale while the event can still retry.

    Events that meet another worker's checkout or check-in lock raise
    ``SnipeItSyncInProgress`` and are redelivered. Delivery ``n`` is handled
    about ``n - 1`` idle intervals after the first, and the event is
    dead-lettered once ``max_delivery_count`` deliveries have been made, so at
    least one attempt must fall a full interval after the lock is retakeable.
    """
    from snipeit_sync_service import IN_FLIGHT_LOCK_SECONDS

    consumer = SnipeItWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )

    interval_seconds = consumer._retry_min_idle_ms / 1000
    last_attempt_seconds = (consumer._max_delivery_count - 1) * interval_seconds
    assert last_attempt_seconds >= IN_FLIGHT_LOCK_SECONDS + interval_seconds
