"""
Unit tests for TaskQueueService.

Tests the ARQ task queue integration for enqueueing jobs
and checking job status.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from arq.connections import RedisSettings
from arq.jobs import JobStatus
from core_shared.integration_constants import (
    IMMICH_ARQ_QUEUE_NAME,
    SNIPEIT_ARQ_QUEUE_NAME,
    STRAVA_ARQ_QUEUE_NAME,
)
from core_shared.tracked_enqueue import JobNotEnqueuedError

from app.core.integrations.exceptions import JobEnqueueError, JobNotFoundException
from app.core.integrations.task_queue_service import ARQ_QUEUE_NAME, TaskQueueService
from app.infrastructure.config import Settings


@dataclass(frozen=True)
class TrackedEnqueueCase:
    """One ``enqueue_*`` method and the tracked job it should queue."""

    method: str
    kwargs: dict[str, Any]
    function: str
    args: tuple[Any, ...]
    queue_name: str
    integration_source: str
    sync_type: str = field(default="smart")


TRACKED_ENQUEUE_CASES = [
    TrackedEnqueueCase(
        method="enqueue_google_sync",
        kwargs={"google_account_email": "a@example.com", "user_id": 123},
        function="sync_google_contacts",
        args=("a@example.com", 123, "smart"),
        queue_name=ARQ_QUEUE_NAME,
        integration_source="google",
    ),
    TrackedEnqueueCase(
        method="enqueue_calendar_sync",
        kwargs={"google_account_email": "a@example.com", "user_id": 123},
        function="sync_calendar_events",
        args=("a@example.com", 123, "smart"),
        queue_name=ARQ_QUEUE_NAME,
        integration_source="google",
    ),
    TrackedEnqueueCase(
        method="enqueue_strava_sync",
        kwargs={"user_id": 123},
        function="sync_strava_activities",
        args=("123", "full"),
        queue_name=STRAVA_ARQ_QUEUE_NAME,
        integration_source="strava",
        sync_type="full",
    ),
    TrackedEnqueueCase(
        method="enqueue_snipeit_sync",
        kwargs={"user_id": 123},
        function="sync_snipeit_assets",
        args=("123", "full"),
        queue_name=SNIPEIT_ARQ_QUEUE_NAME,
        integration_source="snipeit",
        sync_type="full",
    ),
    TrackedEnqueueCase(
        method="enqueue_snipeit_maintenance_sync",
        kwargs={"user_id": 123},
        function="sync_snipeit_maintenances",
        args=("123", "full"),
        queue_name=SNIPEIT_ARQ_QUEUE_NAME,
        integration_source="snipeit",
        sync_type="full",
    ),
    TrackedEnqueueCase(
        method="enqueue_immich_sync",
        kwargs={
            "user_id": 123,
            "sync_type": "incremental",
            "task_name": "sync_immich_albums",
            "integration_source": "immich_album",
        },
        function="sync_immich_albums",
        args=("123", "smart"),
        queue_name=IMMICH_ARQ_QUEUE_NAME,
        integration_source="immich_album",
    ),
]


class TestTaskQueueService:
    """Test cases for TaskQueueService."""

    @pytest.fixture
    def mock_redis_pool(self) -> AsyncMock:
        """Create mock Redis pool."""
        from arq.connections import ArqRedis

        return AsyncMock(spec=ArqRedis)

    @pytest.fixture
    def redis_settings(self) -> RedisSettings:
        """Create Redis settings."""
        return RedisSettings(host="localhost", port=6379, database=0)

    @pytest.fixture
    def mock_settings(self) -> Settings:
        """Create mock Settings instance."""
        return Settings(
            task_queue_job_timeout_seconds=300,
            task_queue_user_job_expiry_hours=24,
        )

    @pytest.fixture
    def service(
        self,
        mock_redis_pool: AsyncMock,
        redis_settings: RedisSettings,
        mock_settings: Settings,
    ) -> TaskQueueService:
        """Create TaskQueueService instance."""
        from app.core.integrations.database import IntegrationDatabaseManager

        mock_db_manager = AsyncMock(spec=IntegrationDatabaseManager)
        return TaskQueueService(
            redis_pool=mock_redis_pool,
            redis_settings=redis_settings,
            settings=mock_settings,
            db_manager=mock_db_manager,
        )

    @pytest.mark.asyncio
    async def test_get_job_status_completed(
        self, service: TaskQueueService, mock_redis_pool: AsyncMock
    ):
        """Test getting status of completed job."""
        job_id = "test-job-123"
        user_id = 123

        # Mock ARQ job info
        mock_job = AsyncMock()
        mock_job_info = MagicMock()
        mock_job_info.job_status = JobStatus.complete
        mock_job_info.enqueue_time = None
        mock_job_info.start_time = None
        mock_job_info.finish_time = None
        mock_job_info.result = {"status": "success", "contacts_processed": 5}
        mock_job.info.return_value = mock_job_info
        mock_job.result.return_value = {"status": "success", "contacts_processed": 5}

        with patch.object(
            service.redis_pool, "hexists", new=AsyncMock(return_value=True)
        ) as mock_hexists:
            with patch(
                "app.core.integrations.task_queue_service.Job"
            ) as mock_job_class:
                mock_job_class.return_value = mock_job

                # Get job status
                status = await service.get_job_status(job_id, user_id)

                # Verify correct calls
                mock_hexists.assert_called_once_with("user_jobs:123", job_id)
                mock_job_class.assert_called_once_with(job_id, redis=mock_redis_pool)
                mock_job.info.assert_called_once()

                # Verify status response
                assert status["job_id"] == job_id
                assert status["status"] == "completed"
                assert status["message"] == "Job completed successfully"
                assert status["result"] == {
                    "status": "success",
                    "contacts_processed": 5,
                }

    @pytest.mark.asyncio
    async def test_get_job_status_running(self, service: TaskQueueService):
        """Test getting status of running job."""
        job_id = "test-job-456"
        user_id = 123

        # Mock user-job ownership verification will be done with patch.object

        # Mock ARQ job info
        mock_job = AsyncMock()
        mock_job_info = MagicMock()
        mock_job_info.job_status = JobStatus.in_progress
        mock_job_info.enqueue_time = None
        mock_job_info.start_time = None
        mock_job_info.finish_time = None
        mock_job_info.result = None
        mock_job.info.return_value = mock_job_info
        mock_job.result.return_value = None

        with patch.object(
            service.redis_pool, "hexists", new=AsyncMock(return_value=True)
        ) as mock_hexists:
            with patch(
                "app.core.integrations.task_queue_service.Job"
            ) as mock_job_class:
                mock_job_class.return_value = mock_job

                # Get job status
                status = await service.get_job_status(job_id, user_id)

                # Verify status response
                mock_hexists.assert_called_once_with("user_jobs:123", job_id)
                assert status["job_id"] == job_id
                assert status["status"] == "running"
                assert status["message"] == "Job is currently being processed"
                assert status["result"] is None

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, service: TaskQueueService):
        """Test getting status of non-existent job."""
        job_id = "non-existent-job"
        user_id = 123

        # Mock user-job ownership verification will be done with patch.object

        # Mock ARQ job info
        mock_job = AsyncMock()
        mock_job.info.return_value = None  # Job not found

        with patch.object(
            service.redis_pool, "hexists", new=AsyncMock(return_value=True)
        ):
            with patch(
                "app.core.integrations.task_queue_service.Job"
            ) as mock_job_class:
                mock_job_class.return_value = mock_job

                # Get job status
                status = await service.get_job_status(job_id, user_id)

                # Verify status response
                assert status["job_id"] == job_id
                assert status["status"] == "not_found"
                assert status["message"] == "Job not found"
                assert status["result"] is None

    @pytest.mark.asyncio
    async def test_get_queue_health_healthy(
        self, service: TaskQueueService, mock_redis_pool: AsyncMock
    ):
        """Test queue health check when healthy."""
        # Mock Redis responses
        mock_redis_pool.ping = AsyncMock(return_value=True)
        # Mock ARQ's queued_jobs method
        mock_jobs = [MagicMock() for _ in range(5)]
        mock_redis_pool.queued_jobs = AsyncMock(return_value=mock_jobs)

        # Get queue health
        health = await service.get_queue_health()

        # Verify Redis calls
        assert (
            mock_redis_pool.ping.call_count == 2
        )  # Called twice for connectivity and response time
        mock_redis_pool.queued_jobs.assert_called_once_with(queue_name="google")

        # Verify health response
        assert health["status"] == "healthy"
        assert health["redis_connected"] is True
        assert health["queue_length"] == 5
        assert "response_time_ms" in health
        assert "checked_at" in health

    @pytest.mark.asyncio
    async def test_get_queue_health_unhealthy(
        self, service: TaskQueueService, mock_redis_pool: AsyncMock
    ):
        """Test queue health check when unhealthy."""
        # Mock Redis to raise exception
        mock_redis_pool.ping = AsyncMock(side_effect=Exception("Connection failed"))

        # Get queue health
        health = await service.get_queue_health()

        # Verify health response
        assert health["status"] == "unhealthy"
        assert health["redis_connected"] is False
        assert health["queue_length"] is None
        assert health["response_time_ms"] is None
        assert "error" in health
        assert "Connection failed" in health["error"]

    def test_get_status_message(self, service: TaskQueueService):
        """Test status message generation."""
        # Mock job info
        mock_job_info = MagicMock()
        mock_job_info.result = {"status": "success"}

        # Test different status messages
        assert (
            service._get_status_message("queued", mock_job_info)
            == "Job is queued and waiting to be processed"
        )
        assert (
            service._get_status_message("running", mock_job_info)
            == "Job is currently being processed"
        )
        assert (
            service._get_status_message("completed", mock_job_info)
            == "Job completed successfully"
        )
        assert (
            service._get_status_message("not_found", mock_job_info)
            == "Job not found or expired"
        )
        assert (
            service._get_status_message("unknown", mock_job_info)
            == "Job status: unknown"
        )

    @pytest.mark.asyncio
    async def test_cancel_job_success(
        self, service: TaskQueueService, mock_redis_pool: AsyncMock
    ):
        """Test successful job cancellation."""
        job_id = "test-job-123"
        user_id = "user-456"

        # Mock Redis for user-job ownership verification
        mock_redis_pool.hexists = AsyncMock(return_value=True)

        # Mock database session and repository
        mock_session = AsyncMock()
        mock_conn = AsyncMock()
        mock_session.connection = AsyncMock(return_value=mock_conn)

        # Create async context manager for db_manager.get_session()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        service.db_manager.get_session = MagicMock(return_value=mock_session_ctx)  # type: ignore[method-assign]

        # Mock repository
        mock_sync_job = MagicMock()
        mock_sync_job.user_id = user_id
        mock_sync_job.status = "cancelled"

        with patch(
            "app.core.integrations.task_queue_service.SyncJobRepository"
        ) as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.get_by_job_id = AsyncMock(return_value=mock_sync_job)
            mock_repo.update_status = AsyncMock(return_value=mock_sync_job)

            # Cancel job
            result = await service.cancel_job(job_id, user_id)

            # Verify result
            assert result["job_id"] == job_id
            assert result["status"] == "cancelled"
            assert "cancellation" in result["message"].lower()

            # Verify repository calls
            mock_repo.update_status.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(
        self, service: TaskQueueService, mock_redis_pool: AsyncMock
    ):
        """Test cancelling a job that doesn't exist."""
        job_id = "nonexistent-job"
        user_id = "user-456"

        # Mock Redis for user-job ownership verification (user owns the job)
        mock_redis_pool.hexists = AsyncMock(return_value=True)

        # Mock database session and repository
        mock_session = AsyncMock()
        mock_conn = AsyncMock()
        mock_session.connection = AsyncMock(return_value=mock_conn)

        # Create async context manager for db_manager.get_session()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        service.db_manager.get_session = MagicMock(return_value=mock_session_ctx)  # type: ignore[method-assign]

        with patch(
            "app.core.integrations.task_queue_service.SyncJobRepository"
        ) as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.get_by_job_id = AsyncMock(return_value=None)
            mock_repo.update_status = AsyncMock(return_value=None)

            # Cancel job should raise JobNotFoundException
            with pytest.raises(JobNotFoundException) as exc_info:
                await service.cancel_job(job_id, user_id)

            # Verify the exception has the correct job_id
            assert exc_info.value.job_id == job_id

    @pytest.mark.asyncio
    async def test_cancel_job_unauthorized(
        self, service: TaskQueueService, mock_redis_pool: AsyncMock
    ):
        """Test cancelling a job owned by another user."""
        job_id = "test-job-123"
        user_id = "user-456"

        # Mock Redis for user-job ownership verification (user does NOT own the job)
        mock_redis_pool.hexists = AsyncMock(return_value=False)

        # Cancel job should raise PermissionError (user doesn't own the job)
        with pytest.raises(PermissionError) as exc_info:
            await service.cancel_job(job_id, user_id)

        # Verify the exception message mentions authorization
        assert "not authorized" in str(exc_info.value).lower()

    @pytest.fixture
    def db_session(self, service: TaskQueueService) -> MagicMock:
        """Stub the integration database session the tracked enqueue writes through."""
        session = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        service.db_manager.get_session = MagicMock(return_value=session_ctx)  # type: ignore[method-assign]
        return session

    @pytest.fixture
    def tracked_enqueue(self, mock_redis_pool: AsyncMock) -> Iterator[AsyncMock]:
        """Patch the shared row-first enqueue the service delegates to."""
        mock_redis_pool.hset = AsyncMock()
        mock_redis_pool.expire = AsyncMock()
        with patch(
            "app.core.integrations.task_queue_service.enqueue_tracked_job",
            new_callable=AsyncMock,
            return_value="tracked-job-1",
        ) as mock:
            yield mock

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", TRACKED_ENQUEUE_CASES, ids=lambda c: c.method)
    async def test_tracked_enqueue_writes_row_through_shared_helper(
        self,
        case: TrackedEnqueueCase,
        service: TaskQueueService,
        mock_redis_pool: AsyncMock,
        db_session: MagicMock,
        tracked_enqueue: AsyncMock,
    ) -> None:
        """Each tracked sync commits its row before queueing, via the shared helper."""
        job_id = await getattr(service, case.method)(**case.kwargs)

        assert job_id == "tracked-job-1"
        tracked_enqueue.assert_awaited_once_with(
            db_session,
            mock_redis_pool,
            case.function,
            *case.args,
            queue_name=case.queue_name,
            user_id="123",
            integration_source=case.integration_source,
            sync_type=case.sync_type,
            otel_carrier=ANY,
            _defer_until=None,
        )
        mock_redis_pool.hset.assert_awaited_once_with(
            "user_jobs:123", "tracked-job-1", "enqueued"
        )

    @pytest.mark.asyncio
    async def test_job_not_enqueued_raises_job_enqueue_error(
        self,
        service: TaskQueueService,
        mock_redis_pool: AsyncMock,
        db_session: MagicMock,
        tracked_enqueue: AsyncMock,
    ) -> None:
        """ARQ returning no job surfaces as JobEnqueueError, with no ownership stored."""
        tracked_enqueue.side_effect = JobNotEnqueuedError("sync_strava_activities", "x")

        with pytest.raises(JobEnqueueError) as exc_info:
            await service.enqueue_strava_sync(user_id=123)

        assert exc_info.value.integration_source == "strava"
        mock_redis_pool.hset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enqueue_error_propagates_without_storing_ownership(
        self,
        service: TaskQueueService,
        mock_redis_pool: AsyncMock,
        db_session: MagicMock,
        tracked_enqueue: AsyncMock,
    ) -> None:
        """A failed enqueue is re-raised and the job is not associated with the user."""
        tracked_enqueue.side_effect = ConnectionError("Redis connection failed")

        with pytest.raises(ConnectionError, match="Redis connection failed"):
            await service.enqueue_google_sync(
                google_account_email="test@example.com", user_id=123
            )

        mock_redis_pool.hset.assert_not_awaited()
