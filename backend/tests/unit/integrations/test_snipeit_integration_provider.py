"""Unit tests for SnipeItIntegrationProvider.

These tests mock the database connection to verify the provider
derives the correct status from the ``user_snipe_it_auth`` and
``sync_jobs`` tables.
"""

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


def _mock_connection(
    auth_row: MagicMock | None = None,
    sync_row: MagicMock | None = None,
) -> AsyncMock:
    """Return a connection mock that returns the given rows for auth and sync queries."""
    call_count = 0

    async def mock_execute(*_args: object, **_kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First query: user_snipe_it_auth
            result.fetchone.return_value = auth_row
        else:
            # Second query: sync_jobs
            result.fetchone.return_value = sync_row
        return result

    connection = AsyncMock()
    connection.execute = mock_execute
    return connection


def _make_auth_row(needs_reauth: bool = False) -> MagicMock:
    """Create a mock auth row."""
    row = MagicMock()
    row.needs_reauth = needs_reauth
    return row


def _make_sync_row(
    last_sync_time: object = None,
    completed_count: int = 0,
    failed_count: int = 0,
) -> MagicMock:
    """Create a mock sync row."""
    row = MagicMock()
    row.last_sync_time = last_sync_time
    row.completed_count = completed_count
    row.failed_count = failed_count
    return row


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
        connection = _mock_connection()
        info = await provider.get_integration_info("user-1", connection)
        assert info.name == "Snipe-IT"

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_disconnected_when_no_auth(
        self,
    ) -> None:
        """Provider returns DISCONNECTED when no user_snipe_it_auth row exists."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection(auth_row=None)
        info = await provider.get_integration_info("user-1", connection)
        assert info.status == IntegrationStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_connected_when_auth_exists(
        self,
    ) -> None:
        """Provider returns CONNECTED when an auth row exists and needs_reauth is false."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection(
            auth_row=_make_auth_row(needs_reauth=False),
            sync_row=_make_sync_row(),
        )
        info = await provider.get_integration_info("user-1", connection)
        assert info.status == IntegrationStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_token_expired_when_needs_reauth(
        self,
    ) -> None:
        """Provider returns TOKEN_EXPIRED when needs_reauth is true."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection(
            auth_row=_make_auth_row(needs_reauth=True),
            sync_row=_make_sync_row(),
        )
        info = await provider.get_integration_info("user-1", connection)
        assert info.status == IntegrationStatus.TOKEN_EXPIRED
        assert info.needs_reauth is True

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_correct_capabilities(self) -> None:
        """Provider declares gear_sync, maintenance_sync, checkout_sync."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection()
        info = await provider.get_integration_info("user-1", connection)

        assert IntegrationCapability.GEAR_SYNC in info.capabilities
        assert IntegrationCapability.MAINTENANCE_SYNC in info.capabilities
        assert IntegrationCapability.CHECKOUT_SYNC in info.capabilities
        assert len(info.capabilities) == 3

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_empty_sync_summary_when_disconnected(
        self,
    ) -> None:
        """Provider returns zeroed sync summary when no auth row exists."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection(auth_row=None)
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
        connection = _mock_connection(auth_row=None)
        info = await provider.get_integration_info("user-1", connection)

        assert info.needs_reauth is False
        assert info.needs_reconsent is False
