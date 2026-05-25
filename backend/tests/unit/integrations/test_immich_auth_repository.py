"""Unit tests for the Immich auth repository."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.integrations.adapters.sql.immich_auth_repository import (
    ImmichSyncSummaryRow,
    SqlImmichAuthRepository,
)


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Return a mock AsyncConnection."""
    return AsyncMock()


@pytest.fixture
def repo(mock_connection: AsyncMock) -> SqlImmichAuthRepository:
    """Return a repository backed by a mock connection."""
    return SqlImmichAuthRepository(mock_connection)


@pytest.mark.asyncio
class TestSqlImmichAuthRepository:
    """Tests for SqlImmichAuthRepository."""

    async def test_is_connected_true(
        self, repo: SqlImmichAuthRepository, mock_connection: AsyncMock
    ) -> None:
        """Return True when auth row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        mock_connection.execute.return_value = mock_result

        assert await repo.is_connected("user-1") is True

    async def test_is_connected_false(
        self, repo: SqlImmichAuthRepository, mock_connection: AsyncMock
    ) -> None:
        """Return False when no auth row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        assert await repo.is_connected("user-1") is False

    async def test_get_sync_summary_with_data(
        self, repo: SqlImmichAuthRepository, mock_connection: AsyncMock
    ) -> None:
        """Return populated summary when sync rows exist."""
        now = datetime.now(UTC)
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.sync_count = 10
        mock_row.error_count = 2
        mock_row.last_sync_time = now
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute.return_value = mock_result

        summary = await repo.get_sync_summary("user-1")

        assert summary == ImmichSyncSummaryRow(
            sync_count=10, error_count=2, last_sync_time=now
        )

    async def test_get_sync_summary_empty(
        self, repo: SqlImmichAuthRepository, mock_connection: AsyncMock
    ) -> None:
        """Return zero summary when no sync rows exist."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        summary = await repo.get_sync_summary("user-1")

        assert summary == ImmichSyncSummaryRow(
            sync_count=0, error_count=0, last_sync_time=None
        )

    async def test_get_sync_summary_handles_null_counts(
        self, repo: SqlImmichAuthRepository, mock_connection: AsyncMock
    ) -> None:
        """Handle null counts from the database gracefully."""
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.sync_count = None
        mock_row.error_count = None
        mock_row.last_sync_time = None
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute.return_value = mock_result

        summary = await repo.get_sync_summary("user-1")

        assert summary == ImmichSyncSummaryRow(
            sync_count=0, error_count=0, last_sync_time=None
        )
