"""Unit tests for IntegrationRegistryService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationInfo,
    IntegrationStatus,
    SyncSummary,
)
from app.core.integrations.registry.service import IntegrationRegistryService


def _make_provider(info: IntegrationInfo) -> MagicMock:
    """Create a mock provider that returns the given IntegrationInfo."""
    provider = MagicMock()
    provider.get_integration_info = AsyncMock(return_value=info)
    return provider


def _make_failing_provider(integration_id: str, error: Exception) -> MagicMock:
    """Create a mock provider that raises an exception."""
    provider = MagicMock()
    provider.get_integration_info = AsyncMock(side_effect=error)
    # The service needs to know the provider's integration ID for error entries.
    # We attach it via the protocol contract: providers must expose ``integration_id``.
    provider.integration_id = integration_id
    return provider


GOOGLE_INFO = IntegrationInfo(
    id="google",
    name="Google",
    status=IntegrationStatus.CONNECTED,
    capabilities=[
        IntegrationCapability.CONTACTS_SYNC,
        IntegrationCapability.CALENDAR_SYNC,
    ],
    sync_summary=SyncSummary(sync_count=10),
)

STRAVA_INFO = IntegrationInfo(
    id="strava",
    name="Strava",
    status=IntegrationStatus.DISCONNECTED,
    capabilities=[IntegrationCapability.ACTIVITY_IMPORT],
)

SNIPEIT_INFO = IntegrationInfo(
    id="snipeit",
    name="Snipe-IT",
    status=IntegrationStatus.DISCONNECTED,
    capabilities=[
        IntegrationCapability.GEAR_SYNC,
        IntegrationCapability.MAINTENANCE_SYNC,
        IntegrationCapability.CHECKOUT_SYNC,
    ],
)


class TestIntegrationRegistryService:
    """Tests for the IntegrationRegistryService."""

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_list(self) -> None:
        """A registry with no providers returns an empty list."""
        service = IntegrationRegistryService(providers=[])
        connection = AsyncMock()

        result = await service.list_integrations(
            user_id="user-1", connection=connection
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_single_provider_returns_one_integration(self) -> None:
        """A single registered provider produces one IntegrationInfo entry."""
        provider = _make_provider(GOOGLE_INFO)
        service = IntegrationRegistryService(providers=[provider])
        connection = AsyncMock()

        result = await service.list_integrations(
            user_id="user-1", connection=connection
        )

        assert len(result) == 1
        assert result[0] == GOOGLE_INFO
        provider.get_integration_info.assert_awaited_once_with("user-1", connection)

    @pytest.mark.asyncio
    async def test_multiple_providers_returns_all_integrations(self) -> None:
        """Multiple providers each produce their own IntegrationInfo entry."""
        google_provider = _make_provider(GOOGLE_INFO)
        strava_provider = _make_provider(STRAVA_INFO)
        service = IntegrationRegistryService(
            providers=[google_provider, strava_provider]
        )
        connection = AsyncMock()

        result = await service.list_integrations(
            user_id="user-1", connection=connection
        )

        assert len(result) == 2
        assert result[0] == GOOGLE_INFO
        assert result[1] == STRAVA_INFO

    @pytest.mark.asyncio
    async def test_provider_error_returns_error_status(self) -> None:
        """When a provider raises, the service returns an error entry for it."""
        failing = _make_failing_provider("broken", RuntimeError("connection refused"))
        service = IntegrationRegistryService(providers=[failing])
        connection = AsyncMock()

        result = await service.list_integrations(
            user_id="user-1", connection=connection
        )

        assert len(result) == 1
        assert result[0].id == "broken"
        assert result[0].status == IntegrationStatus.ERROR

    @pytest.mark.asyncio
    async def test_provider_ordering_preserved(self) -> None:
        """Integrations are returned in provider registration order."""
        strava_provider = _make_provider(STRAVA_INFO)
        google_provider = _make_provider(GOOGLE_INFO)
        # Strava registered first
        service = IntegrationRegistryService(
            providers=[strava_provider, google_provider]
        )
        connection = AsyncMock()

        result = await service.list_integrations(
            user_id="user-1", connection=connection
        )

        assert result[0].id == "strava"
        assert result[1].id == "google"

    @pytest.mark.asyncio
    async def test_healthy_providers_still_returned_when_one_fails(self) -> None:
        """A failing provider does not prevent healthy providers from returning."""
        google_provider = _make_provider(GOOGLE_INFO)
        failing = _make_failing_provider("broken", RuntimeError("timeout"))
        service = IntegrationRegistryService(providers=[google_provider, failing])
        connection = AsyncMock()

        result = await service.list_integrations(
            user_id="user-1", connection=connection
        )

        assert len(result) == 2
        assert result[0] == GOOGLE_INFO
        assert result[1].id == "broken"
        assert result[1].status == IntegrationStatus.ERROR

    @pytest.mark.asyncio
    async def test_three_providers_returns_all_integrations(self) -> None:
        """All three providers (Google, Strava, Snipe-IT) produce entries."""
        google_provider = _make_provider(GOOGLE_INFO)
        strava_provider = _make_provider(STRAVA_INFO)
        snipeit_provider = _make_provider(SNIPEIT_INFO)
        service = IntegrationRegistryService(
            providers=[google_provider, strava_provider, snipeit_provider]
        )
        connection = AsyncMock()

        result = await service.list_integrations(
            user_id="user-1", connection=connection
        )

        assert len(result) == 3
        assert result[0] == GOOGLE_INFO
        assert result[1] == STRAVA_INFO
        assert result[2] == SNIPEIT_INFO
