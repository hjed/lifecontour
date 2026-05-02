"""
Unit tests for StravaIntegrationProvider.

Tests status derivation from user_strava_auth state and capability
declaration without requiring a real database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationStatus,
)
from app.core.integrations.registry.strava_provider import StravaIntegrationProvider


def _mock_connection(
    auth_row: dict[str, object] | None = None,
    sync_row: dict[str, object] | None = None,
) -> AsyncMock:
    """
    Create a mock AsyncConnection that returns given rows.

    Args:
        auth_row: Simulated user_strava_auth row (None = no row).
        sync_row: Simulated sync_jobs aggregation row (None = empty aggregation).
    """
    connection = AsyncMock()

    def _execute_side_effect(stmt, params=None):
        query_str = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
        result = MagicMock()

        if "user_strava_auth" in query_str:
            if auth_row:
                row = MagicMock()
                row.needs_reauth = auth_row.get("needs_reauth", False)
                result.fetchone.return_value = row
            else:
                result.fetchone.return_value = None
        elif "sync_jobs" in query_str:
            row = MagicMock()
            if sync_row:
                row.last_sync_time = sync_row.get("last_sync_time")
                row.completed_count = sync_row.get("completed_count", 0)
                row.failed_count = sync_row.get("failed_count", 0)
            else:
                row.last_sync_time = None
                row.completed_count = 0
                row.failed_count = 0
            result.fetchone.return_value = row

        return result

    connection.execute = AsyncMock(side_effect=_execute_side_effect)
    return connection


class TestStravaProviderStatus:
    """Test status derivation from user_strava_auth state."""

    @pytest.mark.asyncio
    async def test_disconnected_when_no_auth_row(self) -> None:
        """Returns DISCONNECTED when no user_strava_auth row exists."""
        provider = StravaIntegrationProvider()
        connection = _mock_connection(auth_row=None)

        info = await provider.get_integration_info("user_1", connection)

        assert info.status == IntegrationStatus.DISCONNECTED
        assert info.id == "strava"
        assert info.name == "Strava"

    @pytest.mark.asyncio
    async def test_connected_when_auth_exists(self) -> None:
        """Returns CONNECTED when user_strava_auth row exists and needs_reauth is False."""
        provider = StravaIntegrationProvider()
        connection = _mock_connection(auth_row={"needs_reauth": False})

        info = await provider.get_integration_info("user_1", connection)

        assert info.status == IntegrationStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_token_expired_when_needs_reauth(self) -> None:
        """Returns TOKEN_EXPIRED when needs_reauth flag is set."""
        provider = StravaIntegrationProvider()
        connection = _mock_connection(auth_row={"needs_reauth": True})

        info = await provider.get_integration_info("user_1", connection)

        assert info.status == IntegrationStatus.TOKEN_EXPIRED
        assert info.needs_reauth is True


class TestStravaProviderCapabilities:
    """Test capability declaration."""

    @pytest.mark.asyncio
    async def test_capabilities_include_activity_import(self) -> None:
        """Strava provider declares ACTIVITY_IMPORT capability."""
        provider = StravaIntegrationProvider()
        connection = _mock_connection(auth_row=None)

        info = await provider.get_integration_info("user_1", connection)

        assert IntegrationCapability.ACTIVITY_IMPORT in info.capabilities

    @pytest.mark.asyncio
    async def test_needs_reconsent_always_false(self) -> None:
        """Strava does not use reconsent (unlike Google Calendar scopes)."""
        provider = StravaIntegrationProvider()
        connection = _mock_connection(auth_row={"needs_reauth": False})

        info = await provider.get_integration_info("user_1", connection)

        assert info.needs_reconsent is False


class TestStravaProviderSyncSummary:
    """Test sync summary aggregation."""

    @pytest.mark.asyncio
    async def test_sync_summary_empty_when_no_jobs(self) -> None:
        """Sync summary shows zero counts when no sync jobs exist."""
        provider = StravaIntegrationProvider()
        connection = _mock_connection(auth_row={"needs_reauth": False})

        info = await provider.get_integration_info("user_1", connection)

        assert info.sync_summary.sync_count == 0
        assert info.sync_summary.error_count == 0
        assert info.sync_summary.last_sync_time is None

    @pytest.mark.asyncio
    async def test_sync_summary_with_history(self) -> None:
        """Sync summary includes counts from sync_jobs."""
        from datetime import UTC, datetime

        provider = StravaIntegrationProvider()
        last_sync = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        connection = _mock_connection(
            auth_row={"needs_reauth": False},
            sync_row={
                "last_sync_time": last_sync,
                "completed_count": 5,
                "failed_count": 1,
            },
        )

        info = await provider.get_integration_info("user_1", connection)

        assert info.sync_summary.sync_count == 5
        assert info.sync_summary.error_count == 1
        assert info.sync_summary.last_sync_time == last_sync
