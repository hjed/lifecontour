"""Unit tests for SnipeItIntegrationProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationStatus,
)
from app.core.integrations.registry.snipeit_provider import (
    SnipeItIntegrationProvider,
)


def _mock_connection_with_no_auth_table() -> AsyncMock:
    """Return a connection mock where the snipeit_settings query returns no rows."""
    connection = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = None
    connection.execute = AsyncMock(return_value=result)
    return connection


def _mock_connection_with_settings(
    base_url: str = "https://snipeit.example.com",
    snipeit_user_id: str = "42",
) -> AsyncMock:
    """Return a connection mock where snipeit_settings returns a row."""
    connection = AsyncMock()
    settings_row = MagicMock()
    settings_row.base_url = base_url
    settings_row.snipeit_user_id = snipeit_user_id

    result = MagicMock()
    result.fetchone.return_value = settings_row
    connection.execute = AsyncMock(return_value=result)
    return connection


class TestSnipeItIntegrationProvider:
    """Tests for the SnipeItIntegrationProvider."""

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_correct_id(self) -> None:
        """Provider exposes 'snipeit' as its integration_id."""
        provider = SnipeItIntegrationProvider()
        assert provider.integration_id == "snipeit"

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_correct_name(self) -> None:
        """Provider returns 'Snipe-IT' as the human-readable name."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection_with_no_auth_table()

        info = await provider.get_integration_info("user-1", connection)

        assert info.name == "Snipe-IT"

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_disconnected_when_no_settings(
        self,
    ) -> None:
        """Provider returns DISCONNECTED when no snipeit_settings row exists."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection_with_no_auth_table()

        info = await provider.get_integration_info("user-1", connection)

        assert info.status == IntegrationStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_correct_capabilities(self) -> None:
        """Provider declares gear_sync, maintenance_sync, checkout_sync."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection_with_no_auth_table()

        info = await provider.get_integration_info("user-1", connection)

        assert IntegrationCapability.GEAR_SYNC in info.capabilities
        assert IntegrationCapability.MAINTENANCE_SYNC in info.capabilities
        assert IntegrationCapability.CHECKOUT_SYNC in info.capabilities
        assert len(info.capabilities) == 3

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_empty_sync_summary_when_disconnected(
        self,
    ) -> None:
        """Provider returns zeroed sync summary when no settings exist."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection_with_no_auth_table()

        info = await provider.get_integration_info("user-1", connection)

        assert info.sync_summary.last_sync_time is None
        assert info.sync_summary.sync_count == 0
        assert info.sync_summary.error_count == 0

    @pytest.mark.asyncio
    async def test_snipeit_provider_needs_reauth_false_when_disconnected(
        self,
    ) -> None:
        """Provider returns needs_reauth=False when disconnected."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection_with_no_auth_table()

        info = await provider.get_integration_info("user-1", connection)

        assert info.needs_reauth is False
        assert info.needs_reconsent is False
