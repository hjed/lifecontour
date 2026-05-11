"""Unit tests for SnipeItIntegrationProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.integrations.models.snipeit import SnipeItSettings
from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationStatus,
)
from app.core.integrations.registry.snipeit_provider import (
    SnipeItIntegrationProvider,
)


def _mock_connection() -> AsyncMock:
    """Return a minimal connection mock (used to construct the repository)."""
    return AsyncMock()


def _patch_repo(settings: SnipeItSettings | None = None):
    """Patch SqlSnipeItSettingsRepository.get_by_user_id to return *settings*."""
    mock_repo = MagicMock()
    mock_repo.get_by_user_id = AsyncMock(return_value=settings)
    return patch(
        "app.core.integrations.registry.snipeit_provider.SqlSnipeItSettingsRepository",
        return_value=mock_repo,
    )


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

        with _patch_repo(settings=None):
            info = await provider.get_integration_info("user-1", connection)

        assert info.name == "Snipe-IT"

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_disconnected_when_no_settings(
        self,
    ) -> None:
        """Provider returns DISCONNECTED when no snipeit_settings row exists."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection()

        with _patch_repo(settings=None):
            info = await provider.get_integration_info("user-1", connection)

        assert info.status == IntegrationStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_disconnected_even_when_configured(
        self,
    ) -> None:
        """Phase 1: provider returns DISCONNECTED even when settings exist.

        OAuth endpoints don't exist yet, so returning CONNECTED would cause
        the UI to render Connect/Disconnect buttons that 404.
        """
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection()
        settings = SnipeItSettings(
            user_id="user-1",
            base_url="https://snipeit.example.com",
            snipeit_user_id="42",
        )

        with _patch_repo(settings=settings):
            info = await provider.get_integration_info("user-1", connection)

        assert info.status == IntegrationStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_snipeit_provider_returns_correct_capabilities(self) -> None:
        """Provider declares gear_sync, maintenance_sync, checkout_sync."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection()

        with _patch_repo(settings=None):
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
        connection = _mock_connection()

        with _patch_repo(settings=None):
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
        connection = _mock_connection()

        with _patch_repo(settings=None):
            info = await provider.get_integration_info("user-1", connection)

        assert info.needs_reauth is False
        assert info.needs_reconsent is False

    @pytest.mark.asyncio
    async def test_snipeit_provider_handles_db_error_gracefully(
        self,
    ) -> None:
        """Provider returns DISCONNECTED when the DB query raises."""
        provider = SnipeItIntegrationProvider()
        connection = _mock_connection()
        mock_repo = MagicMock()
        mock_repo.get_by_user_id = AsyncMock(
            side_effect=RuntimeError("table does not exist")
        )

        with patch(
            "app.core.integrations.registry.snipeit_provider.SqlSnipeItSettingsRepository",
            return_value=mock_repo,
        ):
            info = await provider.get_integration_info("user-1", connection)

        assert info.status == IntegrationStatus.DISCONNECTED
