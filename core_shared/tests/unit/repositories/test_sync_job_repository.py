"""Unit tests for SyncJobRepository."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core_shared.repositories.sync_job_repository import SyncJobRepository


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Create a mock database connection."""
    return AsyncMock()


@pytest.fixture
def repository(mock_connection: AsyncMock) -> SyncJobRepository:
    """Create a SyncJobRepository instance with mock connection."""
    return SyncJobRepository(mock_connection)


class TestSyncJobRepositoryGetRecentFailures:
    """Test get_recent_failures method."""

    @pytest.mark.asyncio
    async def test_get_recent_failures_with_results(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """Test getting recent failures when failures exist."""
        # Setup mock result
        now = datetime.now(UTC)
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.job_id = "job-123"
        mock_row.user_id = "user-123"
        mock_row.integration_source = "google_contacts"
        mock_row.sync_type = "smart"
        mock_row.status = "failed"
        mock_row.created_at = now
        mock_row.started_at = now
        mock_row.completed_at = now
        mock_row.error_message = "Test error"
        mock_row.contacts_processed = 0
        mock_row.contacts_created = 0
        mock_row.contacts_updated = 0
        mock_row.contacts_deleted = 0
        mock_row.progress = 0
        mock_row.updated_at = now

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        failures = await repository.get_recent_failures(
            integration_source="google_contacts", hours=24, limit=10
        )

        # Verify
        assert len(failures) == 1
        assert failures[0].job_id == "job-123"
        assert failures[0].status == "failed"
        assert failures[0].error_message == "Test error"
        mock_connection.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_recent_failures_no_results(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """Test getting recent failures when no failures exist."""
        # Setup mock result
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        failures = await repository.get_recent_failures(
            integration_source="google_contacts", hours=24, limit=10
        )

        # Verify
        assert len(failures) == 0
        mock_connection.execute.assert_called_once()


class TestSyncJobRepositoryGetJobStatistics:
    """Test get_job_statistics method."""

    @pytest.mark.asyncio
    async def test_get_job_statistics_with_data(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """Test getting job statistics when data exists."""
        # Setup mock result
        mock_row = MagicMock()
        mock_row.total_jobs = 100
        mock_row.completed_jobs = 80
        mock_row.failed_jobs = 10
        mock_row.cancelled_jobs = 5
        mock_row.running_jobs = 3
        mock_row.queued_jobs = 2

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        stats = await repository.get_job_statistics(
            integration_source="google_contacts", hours=24
        )

        # Verify
        assert stats["total_jobs"] == 100
        assert stats["completed_jobs"] == 80
        assert stats["failed_jobs"] == 10
        assert stats["cancelled_jobs"] == 5
        assert stats["running_jobs"] == 3
        assert stats["queued_jobs"] == 2
        assert stats["retry_count"] == 0  # Not yet implemented
        mock_connection.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_statistics_no_data(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """Test getting job statistics when no data exists."""
        # Setup mock result
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        stats = await repository.get_job_statistics(
            integration_source="google_contacts", hours=24
        )

        # Verify
        assert stats["total_jobs"] == 0
        assert stats["completed_jobs"] == 0
        assert stats["failed_jobs"] == 0
        assert stats["cancelled_jobs"] == 0
        assert stats["running_jobs"] == 0
        assert stats["queued_jobs"] == 0
        assert stats["retry_count"] == 0
        mock_connection.execute.assert_called_once()
