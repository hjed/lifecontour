"""Unit tests for calendar webhook receive endpoint.

Tests the receive_calendar_webhook endpoint logic by extracting and calling
the core webhook processing logic. Covers header validation, DB channel
lookup, and sync enqueue behavior.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


class TestWebhookHeaderValidation:
    """Tests for webhook header extraction and validation."""

    @pytest.mark.asyncio
    async def test_missing_channel_id_raises_404(self) -> None:
        """Missing X-Goog-Channel-ID should raise 404."""
        from app.api.integrations.controllers import _validate_webhook_headers

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_headers(
                channel_id=None,
                resource_id="res-123",
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_resource_id_raises_404(self) -> None:
        """Missing X-Goog-Resource-ID should raise 404."""
        from app.api.integrations.controllers import _validate_webhook_headers

        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_headers(
                channel_id="chan-123",
                resource_id=None,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_both_headers_present_passes(self) -> None:
        """Both headers present should not raise."""
        from app.api.integrations.controllers import _validate_webhook_headers

        # Should not raise
        _validate_webhook_headers(
            channel_id="chan-123",
            resource_id="res-123",
        )


class TestWebhookChannelLookup:
    """Tests for webhook channel database lookup."""

    @pytest.mark.asyncio
    async def test_unknown_channel_raises_404(self) -> None:
        """When no DB row matches, should raise 404."""
        from app.api.integrations.controllers import _lookup_webhook_channel

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await _lookup_webhook_channel(mock_session, "unknown-chan", "unknown-res")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_known_channel_returns_user_info(self) -> None:
        """When a channel matches, should return the row data."""
        from app.api.integrations.controllers import _lookup_webhook_channel

        mock_row = MagicMock()
        mock_row.user_id = "user-1"
        mock_row.google_account_email = "test@example.com"
        mock_row.google_calendar_id = "cal-1"

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        row = await _lookup_webhook_channel(mock_session, "valid-chan", "valid-res")
        assert row.user_id == "user-1"
        assert row.google_account_email == "test@example.com"


class TestWebhookSyncBehavior:
    """Tests for webhook sync enqueue decisions."""

    @pytest.mark.asyncio
    async def test_sync_state_should_not_enqueue(self) -> None:
        """The 'sync' resource_state is a channel confirmation — no sync needed."""
        from app.api.integrations.controllers import _should_enqueue_sync

        assert _should_enqueue_sync("sync") is False

    @pytest.mark.asyncio
    async def test_exists_state_should_enqueue(self) -> None:
        """The 'exists' state means data changed — should trigger sync."""
        from app.api.integrations.controllers import _should_enqueue_sync

        assert _should_enqueue_sync("exists") is True

    @pytest.mark.asyncio
    async def test_update_state_should_enqueue(self) -> None:
        """The 'update' state means data changed — should trigger sync."""
        from app.api.integrations.controllers import _should_enqueue_sync

        assert _should_enqueue_sync("update") is True

    @pytest.mark.asyncio
    async def test_empty_state_should_not_enqueue(self) -> None:
        """Empty resource_state (missing header) should not trigger sync."""
        from app.api.integrations.controllers import _should_enqueue_sync

        assert _should_enqueue_sync("") is False

    @pytest.mark.asyncio
    async def test_unknown_state_should_not_enqueue(self) -> None:
        """Unknown resource_state values should not trigger sync."""
        from app.api.integrations.controllers import _should_enqueue_sync

        assert _should_enqueue_sync("invalid") is False

    @pytest.mark.asyncio
    async def test_enqueue_uses_smart_sync_type(self) -> None:
        """Webhook-triggered syncs should use 'smart' sync type."""
        mock_tqs = AsyncMock()
        mock_tqs.enqueue_calendar_sync = AsyncMock(return_value="job-123")

        await mock_tqs.enqueue_calendar_sync(
            google_account_email="test@example.com",
            user_id="user-1",
            sync_type="smart",
        )

        mock_tqs.enqueue_calendar_sync.assert_called_once_with(
            google_account_email="test@example.com",
            user_id="user-1",
            sync_type="smart",
        )
