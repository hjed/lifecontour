"""
Unit tests for TaskQueueService.

Tests the ARQ task queue integration for enqueueing jobs
and checking job status.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq.connections import RedisSettings
from arq.jobs import JobStatus
from redis.asyncio import Redis

from app.core.integrations.task_queue_service import TaskQueueService


class TestTaskQueueService:
    """Test cases for TaskQueueService."""

    @pytest.fixture
    def mock_redis_pool(self) -> AsyncMock:
        """Create mock Redis pool."""
        return AsyncMock(spec=Redis)

    @pytest.fixture
    def redis_settings(self) -> RedisSettings:
        """Create Redis settings."""
        return RedisSettings(host="localhost", port=6379, database=0)

    @pytest.fixture
    def service(
        self, mock_redis_pool: AsyncMock, redis_settings: RedisSettings
    ) -> TaskQueueService:
        """Create TaskQueueService instance."""
        return TaskQueueService(
            redis_pool=mock_redis_pool, redis_settings=redis_settings
        )

    @pytest.mark.asyncio
    async def test_enqueue_google_contacts_sync_success(
        self, service: TaskQueueService, mock_redis_pool: AsyncMock
    ):
        """Test successful job enqueueing."""
        # Mock ARQ pool and job
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job-123"
        mock_pool.enqueue_job.return_value = mock_job

        with patch(
            "app.core.integrations.task_queue_service.create_pool"
        ) as mock_create_pool:
            mock_create_pool.return_value = mock_pool

            # Mock Redis operations for user-job association
            mock_redis_pool.hset = AsyncMock()
            mock_redis_pool.expire = AsyncMock()

            # Enqueue job
            job_id = await service.enqueue_google_contacts_sync(
                google_account_email="test@example.com", user_id=123, sync_type="smart"
            )

            # Verify job was enqueued correctly
            mock_create_pool.assert_called_once_with(service.redis_settings)
            mock_pool.enqueue_job.assert_called_once_with(
                "sync_google_contacts",
                "test@example.com",
                123,
                "smart",
                _job_timeout=300,
                _defer_until=None,
            )
            mock_pool.close.assert_called_once()

            assert job_id == "test-job-123"

            # Verify user-job association was stored
            mock_redis_pool.hset.assert_called_once_with(
                "user_jobs:123", "test-job-123", "enqueued"
            )
            mock_redis_pool.expire.assert_called_once_with("user_jobs:123", 86400)

    @pytest.mark.asyncio
    async def test_enqueue_google_contacts_sync_failure(
        self, service: TaskQueueService
    ):
        """Test job enqueueing failure."""
        with patch(
            "app.core.integrations.task_queue_service.create_pool"
        ) as mock_create_pool:
            mock_create_pool.side_effect = Exception("Redis connection failed")

            # Should raise exception
            with pytest.raises(Exception) as exc_info:
                await service.enqueue_google_contacts_sync(
                    google_account_email="test@example.com",
                    user_id=123,
                    sync_type="smart",
                )

            assert "Redis connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_job_status_completed(self, service: TaskQueueService):
        """Test getting status of completed job."""
        job_id = "test-job-123"
        user_id = 123

        # Mock user-job ownership verification
        service.redis_pool.hexists = AsyncMock(return_value=True)

        # Mock ARQ pool and job info
        mock_pool = AsyncMock()
        mock_job = AsyncMock()
        mock_job_info = MagicMock()
        mock_job_info.job_status = JobStatus.complete
        mock_job_info.enqueue_time = None
        mock_job_info.start_time = None
        mock_job_info.finish_time = None
        mock_job_info.result = {"status": "success", "contacts_processed": 5}
        mock_job.info.return_value = mock_job_info

        with patch.object(
            service.redis_pool, "hexists", new=AsyncMock(return_value=True)
        ) as mock_hexists:
            with patch(
                "app.core.integrations.task_queue_service.create_pool"
            ) as mock_create_pool:
                mock_create_pool.return_value = mock_pool
                with patch(
                    "app.core.integrations.task_queue_service.Job"
                ) as mock_job_class:
                    mock_job_class.return_value = mock_job

                    # Get job status
                    status = await service.get_job_status(job_id, user_id)

                    # Verify correct calls
                    mock_hexists.assert_called_once_with("user_jobs:123", job_id)
                mock_create_pool.assert_called_once_with(service.redis_settings)
                mock_job_class.assert_called_once_with(job_id, redis=mock_pool)
                mock_job.info.assert_called_once()
                mock_pool.close.assert_called_once()

                # Verify status response
                assert status["job_id"] == job_id
                assert status["status"] == "completed"
                assert status["message"] == "Job completed successfully"
                assert status["result"] == {"status": "success", "contacts_processed": 5}

    @pytest.mark.asyncio
    async def test_get_job_status_running(self, service: TaskQueueService):
        """Test getting status of running job."""
        job_id = "test-job-456"
        user_id = 123

        # Mock user-job ownership verification
        service.redis_pool.hexists = AsyncMock(return_value=True)

        # Mock ARQ pool and job info
        mock_pool = AsyncMock()
        mock_job = AsyncMock()
        mock_job_info = MagicMock()
        mock_job_info.job_status = JobStatus.in_progress
        mock_job_info.enqueue_time = None
        mock_job_info.start_time = None
        mock_job_info.finish_time = None
        mock_job_info.result = None
        mock_job.info.return_value = mock_job_info

        with patch.object(
            service.redis_pool, "hexists", new=AsyncMock(return_value=True)
        ) as mock_hexists:
            with patch(
                "app.core.integrations.task_queue_service.create_pool"
            ) as mock_create_pool:
                mock_create_pool.return_value = mock_pool
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

        # Mock ARQ pool and job info
        mock_pool = AsyncMock()
        mock_job = AsyncMock()
        mock_job.info.return_value = None  # Job not found

        with patch.object(
            service.redis_pool, "hexists", new=AsyncMock(return_value=True)
        ):
            with patch(
                "app.core.integrations.task_queue_service.create_pool"
            ) as mock_create_pool:
                mock_create_pool.return_value = mock_pool
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
        mock_redis_pool.llen = AsyncMock(return_value=5)

        # Get queue health
        health = await service.get_queue_health()

        # Verify Redis calls
        assert (
            mock_redis_pool.ping.call_count == 2
        )  # Called twice for connectivity and response time
        mock_redis_pool.llen.assert_called_once_with("arq:queue")

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
