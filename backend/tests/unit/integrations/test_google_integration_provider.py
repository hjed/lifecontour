"""Unit tests for GoogleIntegrationProvider."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.integrations.registry.google_provider import (
    GoogleIntegrationProvider,
)
from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationStatus,
)


def _make_connection(
    *,
    auth_rows: list[dict[str, object]] | None = None,
    completed_sync_row: dict[str, object] | None = None,
    completed_sync_count: int = 0,
    failed_sync_count: int = 0,
) -> AsyncMock:
    """Create a mock AsyncConnection that returns data for Google provider queries.

    The provider issues two SQL queries via ``connection.execute``:
      1. ``user_google_auth`` — returns auth_rows (or empty)
      2. Sync-job summary query — returns sync stats

    We use ``side_effect`` to map calls in order.
    """
    connection = AsyncMock()

    # Build mock results for auth query
    if auth_rows is None:
        auth_rows = []

    auth_result = MagicMock()
    auth_result.fetchall.return_value = [_dict_to_row(row) for row in auth_rows]

    # Build mock result for sync summary query
    sync_summary = {
        "last_sync_time": (
            completed_sync_row["completed_at"] if completed_sync_row else None
        ),
        "completed_count": completed_sync_count,
        "failed_count": failed_sync_count,
    }
    sync_result = MagicMock()
    sync_result.fetchone.return_value = _dict_to_row(sync_summary)

    connection.execute = AsyncMock(side_effect=[auth_result, sync_result])
    return connection


def _dict_to_row(data: dict[str, object]) -> MagicMock:
    """Create a mock Row-like object from a dict with attribute access."""
    row = MagicMock()
    for key, value in data.items():
        setattr(row, key, value)
    row._mapping = data
    return row


class TestGoogleIntegrationProvider:
    """Tests for GoogleIntegrationProvider status derivation."""

    @pytest.mark.asyncio
    async def test_disconnected_status_when_no_tokens(self) -> None:
        """No row in user_google_auth means disconnected."""
        connection = _make_connection(auth_rows=[])
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert result.id == "google"
        assert result.status == IntegrationStatus.DISCONNECTED
        assert result.needs_reauth is False
        assert result.needs_reconsent is False

    @pytest.mark.asyncio
    async def test_connected_status_with_valid_tokens(self) -> None:
        """Valid, non-expired tokens with full scopes → connected."""
        connection = _make_connection(
            auth_rows=[
                {
                    "granted_scopes": "https://www.googleapis.com/auth/contacts https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly",
                    "needs_reauth": False,
                }
            ],
            completed_sync_count=5,
        )
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert result.status == IntegrationStatus.CONNECTED
        assert result.needs_reauth is False
        assert result.needs_reconsent is False

    @pytest.mark.asyncio
    async def test_token_expired_status_when_needs_reauth(self) -> None:
        """needs_reauth flag set → token_expired status."""
        connection = _make_connection(
            auth_rows=[
                {
                    "granted_scopes": "https://www.googleapis.com/auth/contacts https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly",
                    "needs_reauth": True,
                }
            ],
        )
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert result.status == IntegrationStatus.TOKEN_EXPIRED
        assert result.needs_reauth is True

    @pytest.mark.asyncio
    async def test_needs_reconsent_when_missing_calendar_scopes(self) -> None:
        """Partial scopes (contacts only, no calendar) → needs_reconsent."""
        connection = _make_connection(
            auth_rows=[
                {
                    "granted_scopes": "https://www.googleapis.com/auth/contacts",
                    "needs_reauth": False,
                }
            ],
        )
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert result.status == IntegrationStatus.CONNECTED
        assert result.needs_reconsent is True

    @pytest.mark.asyncio
    async def test_sync_summary_from_sync_jobs(self) -> None:
        """Derives last sync time and count from SyncJob records."""
        last_sync = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
        connection = _make_connection(
            auth_rows=[
                {
                    "granted_scopes": "https://www.googleapis.com/auth/contacts https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly",
                    "needs_reauth": False,
                }
            ],
            completed_sync_row={"completed_at": last_sync},
            completed_sync_count=42,
            failed_sync_count=3,
        )
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert result.sync_summary.last_sync_time == last_sync
        assert result.sync_summary.sync_count == 42
        assert result.sync_summary.error_count == 3

    @pytest.mark.asyncio
    async def test_sync_summary_with_no_sync_jobs(self) -> None:
        """No sync jobs → null last_sync_time, zero counts."""
        connection = _make_connection(auth_rows=[])
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert result.sync_summary.last_sync_time is None
        assert result.sync_summary.sync_count == 0
        assert result.sync_summary.error_count == 0

    @pytest.mark.asyncio
    async def test_capabilities_include_contacts_and_calendar(self) -> None:
        """Google provider declares contacts_sync and calendar_sync capabilities."""
        connection = _make_connection(auth_rows=[])
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert IntegrationCapability.CONTACTS_SYNC in result.capabilities
        assert IntegrationCapability.CALENDAR_SYNC in result.capabilities

    @pytest.mark.asyncio
    async def test_error_count_from_failed_sync_jobs(self) -> None:
        """Counts failed jobs in sync_summary.error_count."""
        connection = _make_connection(
            auth_rows=[
                {
                    "granted_scopes": "https://www.googleapis.com/auth/contacts",
                    "needs_reauth": False,
                }
            ],
            failed_sync_count=7,
        )
        provider = GoogleIntegrationProvider()

        result = await provider.get_integration_info("user-1", connection)

        assert result.sync_summary.error_count == 7

    @pytest.mark.asyncio
    async def test_integration_id_attribute(self) -> None:
        """Provider exposes integration_id for error reporting."""
        provider = GoogleIntegrationProvider()
        assert provider.integration_id == "google"
