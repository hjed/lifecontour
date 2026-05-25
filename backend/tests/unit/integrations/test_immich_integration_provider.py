"""Unit tests for the Immich integration provider."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.integrations.registry.immich_provider import ImmichIntegrationProvider
from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationStatus,
)


@pytest.fixture
def provider() -> ImmichIntegrationProvider:
    """Return an ImmichIntegrationProvider instance."""
    return ImmichIntegrationProvider()


@pytest.mark.asyncio
class TestImmichIntegrationProvider:
    """Tests for the Immich integration provider."""

    async def test_get_integration_info_not_connected(
        self, provider: ImmichIntegrationProvider
    ) -> None:
        """Test returning disconnected status when no auth row exists."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        info = await provider.get_integration_info("user-1", mock_session)

        assert info.id == "immich"
        assert info.name == "Immich"
        assert info.status == IntegrationStatus.DISCONNECTED
        assert not info.needs_reauth
        assert IntegrationCapability.CONTACTS_SYNC in info.capabilities
        assert IntegrationCapability.ALBUM_SYNC in info.capabilities
        assert info.sync_summary.sync_count == 0
        assert info.sync_summary.error_count == 0

    async def test_get_integration_info_connected_no_syncs(
        self, provider: ImmichIntegrationProvider
    ) -> None:
        """Test returning connected status when auth row exists."""
        mock_session = AsyncMock()
        mock_auth_result = MagicMock()

        # Mock auth query returning a row
        mock_auth_row = MagicMock()
        mock_auth_result.fetchone.return_value = mock_auth_row

        # Mock sync query returning 0 counts
        mock_sync_result = MagicMock()
        mock_sync_row = MagicMock()
        mock_sync_row.sync_count = 0
        mock_sync_row.error_count = 0
        mock_sync_row.last_sync_time = None
        mock_sync_result.fetchone.return_value = mock_sync_row

        mock_session.execute.side_effect = [mock_auth_result, mock_sync_result]

        info = await provider.get_integration_info("user-1", mock_session)

        assert info.status == IntegrationStatus.CONNECTED
        assert info.sync_summary.sync_count == 0

    async def test_get_integration_info_with_sync_history(
        self, provider: ImmichIntegrationProvider
    ) -> None:
        """Test returning sync summary data."""
        mock_session = AsyncMock()
        mock_auth_result = MagicMock()
        mock_auth_row = MagicMock()
        mock_auth_result.fetchone.return_value = mock_auth_row

        now = datetime.now(UTC)
        mock_sync_result = MagicMock()
        mock_sync_row = MagicMock()
        mock_sync_row.sync_count = 10
        mock_sync_row.error_count = 2
        mock_sync_row.last_sync_time = now
        mock_sync_result.fetchone.return_value = mock_sync_row

        mock_session.execute.side_effect = [mock_auth_result, mock_sync_result]

        info = await provider.get_integration_info("user-1", mock_session)

        assert info.status == IntegrationStatus.CONNECTED
        assert info.sync_summary.sync_count == 10
        assert info.sync_summary.error_count == 2
        assert info.sync_summary.last_sync_time == now
