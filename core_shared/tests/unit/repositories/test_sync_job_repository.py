"""Unit tests for SyncJobRepository."""

from datetime import UTC, datetime
from typing import Any
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
        mock_row.integration_source = "google"
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
            integration_source="google", hours=24, limit=10
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
            integration_source="google", hours=24, limit=10
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
            integration_source="google", hours=24
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
            integration_source="google", hours=24
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


def _full_mock_row(**overrides: Any) -> MagicMock:
    """Build a mock DB row covering every sync_jobs column (incl. hierarchy)."""
    now = datetime.now(UTC)
    row = MagicMock()
    row.id = 1
    row.job_id = "job-1"
    row.user_id = "user-1"
    row.integration_source = "immich"
    row.sync_type = "full"
    row.status = "queued"
    row.created_at = now
    row.started_at = None
    row.completed_at = None
    row.error_message = None
    row.contacts_processed = None
    row.contacts_created = None
    row.contacts_updated = None
    row.contacts_deleted = None
    row.progress = None
    row.updated_at = now
    row.parent_job_id = None
    row.expected_children = 0
    row.completed_children = 0
    row.failed_children = 0
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class TestSyncJobRepositoryRowMapping:
    """Test _row_to_sync_job maps the new hierarchy columns."""

    def test_row_to_sync_job_maps_hierarchy_columns(
        self, repository: SyncJobRepository
    ) -> None:
        """The row mapper surfaces parent_job_id and the child counters."""
        row = _full_mock_row(
            parent_job_id="parent-1",
            expected_children=3,
            completed_children=2,
            failed_children=1,
        )

        job = repository._row_to_sync_job(row)

        assert job.parent_job_id == "parent-1"
        assert job.expected_children == 3
        assert job.completed_children == 2
        assert job.failed_children == 1


class TestSyncJobRepositoryCreateChild:
    """Test create() with a parent link."""

    @pytest.mark.asyncio
    async def test_create_passes_parent_job_id(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """create() forwards parent_job_id into the INSERT params."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _full_mock_row(
            job_id="child-1", parent_job_id="parent-1"
        )
        mock_connection.execute = AsyncMock(return_value=mock_result)

        job = await repository.create(
            job_id="child-1",
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
            parent_job_id="parent-1",
        )

        assert job.parent_job_id == "parent-1"
        _query, params = mock_connection.execute.call_args.args
        assert params["parent_job_id"] == "parent-1"
        assert "parent_job_id" in str(_query)

    @pytest.mark.asyncio
    async def test_create_defaults_parent_job_id_to_none(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """Top-level jobs created without a parent pass parent_job_id=None."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _full_mock_row()
        mock_connection.execute = AsyncMock(return_value=mock_result)

        await repository.create(
            job_id="job-1",
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
        )

        _query, params = mock_connection.execute.call_args.args
        assert params["parent_job_id"] is None


class TestSyncJobRepositorySetExpectedChildren:
    """Test set_expected_children()."""

    @pytest.mark.asyncio
    async def test_set_expected_children_builds_update(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """set_expected_children issues an UPDATE for the parent job."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _full_mock_row(
            job_id="parent-1", expected_children=5
        )
        mock_connection.execute = AsyncMock(return_value=mock_result)

        job = await repository.set_expected_children("parent-1", 5)

        assert job is not None
        assert job.expected_children == 5
        query, params = mock_connection.execute.call_args.args
        sql = str(query)
        assert "UPDATE sync_jobs" in sql
        assert "expected_children = :expected_children" in sql
        assert params["expected_children"] == 5
        assert params["job_id"] == "parent-1"

    @pytest.mark.asyncio
    async def test_set_expected_children_returns_none_when_missing(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """set_expected_children returns None when the job does not exist."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute = AsyncMock(return_value=mock_result)

        result = await repository.set_expected_children("missing", 5)

        assert result is None

    @pytest.mark.asyncio
    async def test_set_expected_children_rejects_negative(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """A negative expected_children is rejected before touching the DB."""
        mock_connection.execute = AsyncMock()

        with pytest.raises(ValueError, match="non-negative"):
            await repository.set_expected_children("parent-1", -1)

        mock_connection.execute.assert_not_called()


class TestSyncJobRepositoryIncrementCounters:
    """Test atomic child-counter increments."""

    @pytest.mark.asyncio
    async def test_increment_completed_children_issues_atomic_update(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """increment_completed_children runs a single atomic SQL increment."""
        mock_connection.execute = AsyncMock(return_value=MagicMock(rowcount=1))

        await repository.increment_completed_children("parent-1")

        mock_connection.execute.assert_called_once()
        query, params = mock_connection.execute.call_args.args
        sql = str(query)
        assert "completed_children = completed_children + 1" in sql
        assert "failed_children" not in sql
        assert params["parent_job_id"] == "parent-1"

    @pytest.mark.asyncio
    async def test_increment_failed_children_issues_atomic_update(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """increment_failed_children runs a single atomic SQL increment."""
        mock_connection.execute = AsyncMock(return_value=MagicMock(rowcount=1))

        await repository.increment_failed_children("parent-1")

        mock_connection.execute.assert_called_once()
        query, params = mock_connection.execute.call_args.args
        sql = str(query)
        assert "failed_children = failed_children + 1" in sql
        assert "completed_children" not in sql
        assert params["parent_job_id"] == "parent-1"

    @pytest.mark.asyncio
    async def test_increment_raises_when_parent_missing(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """A no-op UPDATE (unknown parent) raises instead of silently dropping."""
        mock_connection.execute = AsyncMock(return_value=MagicMock(rowcount=0))

        with pytest.raises(ValueError, match="no sync job with job_id"):
            await repository.increment_completed_children("missing-parent")


class TestSyncJobRepositoryListChildren:
    """Test list_children()."""

    @pytest.mark.asyncio
    async def test_list_children_filters_by_parent(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """list_children selects rows linked to the given parent."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            _full_mock_row(job_id="child-1", parent_job_id="parent-1"),
            _full_mock_row(job_id="child-2", parent_job_id="parent-1"),
        ]
        mock_connection.execute = AsyncMock(return_value=mock_result)

        children = await repository.list_children("parent-1")

        assert len(children) == 2
        assert {c.job_id for c in children} == {"child-1", "child-2"}
        query, params = mock_connection.execute.call_args.args
        assert "parent_job_id = :parent_job_id" in str(query)
        assert params["parent_job_id"] == "parent-1"


class TestSyncJobRepositoryAggregateChildren:
    """Test aggregate_children()."""

    @pytest.mark.asyncio
    async def test_aggregate_children_returns_status_counts(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """aggregate_children returns total/completed/failed counts."""
        mock_row = MagicMock()
        mock_row.total = 5
        mock_row.completed = 3
        mock_row.failed = 1
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute = AsyncMock(return_value=mock_result)

        counts = await repository.aggregate_children("parent-1")

        assert counts["total"] == 5
        assert counts["completed"] == 3
        assert counts["failed"] == 1
        query, params = mock_connection.execute.call_args.args
        assert params["parent_job_id"] == "parent-1"

    @pytest.mark.asyncio
    async def test_aggregate_children_handles_no_children(
        self, repository: SyncJobRepository, mock_connection: AsyncMock
    ) -> None:
        """aggregate_children returns zeroes when the parent has no children."""
        mock_row = MagicMock()
        mock_row.total = 0
        mock_row.completed = 0
        mock_row.failed = 0
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute = AsyncMock(return_value=mock_result)

        counts = await repository.aggregate_children("parent-1")

        assert counts == {"total": 0, "completed": 0, "failed": 0}
