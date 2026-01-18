"""
Unit tests for IntegrationHealthService.

Tests the health monitoring functionality for integration services
including Redis, workers, and external APIs.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.asyncio import Redis

from app.core.integrations.health_service import IntegrationHealthService


class TestIntegrationHealthService:
    """Test cases for IntegrationHealthService."""

    @pytest.fixture
    def mock_redis_pool(self) -> AsyncMock:
        """Create mock Redis pool."""
        return AsyncMock(spec=Redis)

    @pytest.fixture
    def mock_db_manager(self) -> MagicMock:
        """Create mock database manager."""
        return MagicMock()

    @pytest.fixture
    def service(
        self, mock_redis_pool: AsyncMock, mock_db_manager: MagicMock
    ) -> IntegrationHealthService:
        """Create IntegrationHealthService instance."""
        return IntegrationHealthService(
            redis_pool=mock_redis_pool, db_manager=mock_db_manager
        )

    @pytest.mark.asyncio
    async def test_get_overall_health_all_healthy(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test overall health when all services are healthy."""
        # Mock Redis responses for healthy state
        mock_redis_pool.ping = AsyncMock(return_value=True)
        mock_redis_pool.info = AsyncMock(
            return_value={
                "used_memory_human": "1.5M",
                "connected_clients": 3,
            }
        )
        mock_redis_pool.llen = AsyncMock(return_value=2)

        # Mock aiohttp.ClientSession for external API check
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # Get overall health
            health = await service.get_overall_health()

        # Verify overall status
        assert health["status"] == "healthy"
        assert "timestamp" in health
        assert "services" in health
        assert health["version"] == "1.0.0"

        # Verify individual service statuses
        services = health["services"]
        assert services["redis"]["status"] == "healthy"
        assert services["google_contacts_worker"]["status"] == "healthy"
        assert services["google_api"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_overall_health_redis_unhealthy(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test overall health when Redis is unhealthy."""
        # Mock Redis to fail
        mock_redis_pool.ping = AsyncMock(side_effect=Exception("Connection failed"))

        # Get overall health
        health = await service.get_overall_health()

        # Verify overall status is unhealthy
        assert health["status"] == "unhealthy"

        # Verify Redis service is unhealthy
        services = health["services"]
        assert services["redis"]["status"] == "unhealthy"
        assert "Connection failed" in services["redis"]["error"]

    @pytest.mark.asyncio
    async def test_check_redis_health_success(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test Redis health check when healthy."""
        # Mock Redis responses
        mock_redis_pool.ping = AsyncMock(return_value=True)
        mock_redis_pool.info = AsyncMock(
            return_value={
                "used_memory_human": "2.1M",
                "connected_clients": 5,
            }
        )
        mock_redis_pool.llen = AsyncMock(return_value=3)

        # Check Redis health
        health = await service._check_redis_health()

        # Verify health response
        assert health["status"] == "healthy"
        assert "response_time_ms" in health
        assert health["memory_usage"] == "2.1M"
        assert health["connected_clients"] == 5
        assert health["queue_length"] == 3
        assert "last_checked" in health

        # Verify Redis calls
        mock_redis_pool.ping.assert_called_once()
        mock_redis_pool.info.assert_called_once()
        mock_redis_pool.llen.assert_called_once_with("arq:queue")

    @pytest.mark.asyncio
    async def test_check_redis_health_failure(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test Redis health check when unhealthy."""
        # Mock Redis to fail
        mock_redis_pool.ping = AsyncMock(side_effect=Exception("Redis down"))

        # Check Redis health
        health = await service._check_redis_health()

        # Verify health response
        assert health["status"] == "unhealthy"
        assert "Redis down" in health["error"]
        assert "last_checked" in health

    @pytest.mark.asyncio
    async def test_check_worker_health_success(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test worker health check when healthy."""
        # Mock Redis for recent job count
        mock_redis_pool.llen = AsyncMock(return_value=1)

        # Check worker health
        health = await service._check_worker_health()

        # Verify health response
        assert health["status"] == "healthy"
        assert health["queue_length"] == 1
        assert health["worker_version"] == "1.0.0"
        assert "last_checked" in health

    @pytest.mark.asyncio
    async def test_check_worker_health_failure(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test worker health check when unhealthy."""
        # Mock Redis to fail
        mock_redis_pool.llen = AsyncMock(
            side_effect=Exception("Redis connection failed")
        )

        # Check worker health
        health = await service._check_worker_health()

        # Verify health response
        assert health["status"] == "unhealthy"
        assert "Redis connection failed" in health["error"]
        assert "last_checked" in health

    @pytest.mark.asyncio
    async def test_check_external_api_health_success(
        self, service: IntegrationHealthService
    ):
        """Test external API health check when healthy."""
        # Mock aiohttp.ClientSession for external API check
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # Check external API health
            health = await service._check_external_api_health()

        # Verify health response
        assert health["status"] == "healthy"
        assert "response_time_ms" in health
        assert "last_successful_call" in health
        assert health["endpoint_tested"] == "Google OAuth2 discovery"
        assert "last_checked" in health

    @pytest.mark.asyncio
    async def test_check_service_connectivity_redis(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test service connectivity check for Redis."""
        # Mock Redis responses
        mock_redis_pool.ping = AsyncMock(return_value=True)
        mock_redis_pool.info = AsyncMock(return_value={})
        mock_redis_pool.llen = AsyncMock(return_value=0)

        # Check Redis connectivity
        health = await service.check_service_connectivity("redis")

        # Verify it returns Redis health
        assert health["status"] == "healthy"
        assert "response_time_ms" in health

    @pytest.mark.asyncio
    async def test_check_service_connectivity_worker(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test service connectivity check for worker."""
        # Mock Redis for worker health
        mock_redis_pool.llen = AsyncMock(return_value=0)

        # Check worker connectivity
        health = await service.check_service_connectivity("worker")

        # Verify it returns worker health
        assert health["status"] == "healthy"
        assert health["queue_length"] == 0

    @pytest.mark.asyncio
    async def test_check_service_connectivity_google_api(
        self, service: IntegrationHealthService
    ):
        """Test service connectivity check for Google API."""
        # Mock aiohttp.ClientSession for external API check
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # Check Google API connectivity
            health = await service.check_service_connectivity("google_api")

        # Verify it returns Google API health
        assert health["status"] == "healthy"
        assert "response_time_ms" in health

    @pytest.mark.asyncio
    async def test_check_service_connectivity_unknown(
        self, service: IntegrationHealthService
    ):
        """Test service connectivity check for unknown service."""
        # Check unknown service
        health = await service.check_service_connectivity("unknown_service")

        # Verify it returns unknown status
        assert health["status"] == "unknown"
        assert "Unknown service: unknown_service" in health["error"]

    @pytest.mark.asyncio
    async def test_get_recent_job_count_success(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test getting recent job count when successful."""
        # Mock Redis response
        mock_redis_pool.llen = AsyncMock(return_value=5)

        # Get recent job count
        count = await service._get_recent_job_count()

        # Verify count
        assert count == 5
        mock_redis_pool.llen.assert_called_once_with("arq:queue")

    @pytest.mark.asyncio
    async def test_get_recent_job_count_failure(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test getting recent job count when Redis fails."""
        # Mock Redis to fail
        mock_redis_pool.llen = AsyncMock(side_effect=Exception("Redis error"))

        # Get recent job count
        count = await service._get_recent_job_count()

        # Verify it returns 0 on failure
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_overall_health_includes_queue_metrics(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test that overall health includes queue metrics."""
        # Mock Redis responses
        mock_redis_pool.ping = AsyncMock(return_value=True)
        mock_redis_pool.info = AsyncMock(
            return_value={
                "used_memory_human": "1M",
                "connected_clients": 5,
            }
        )
        mock_redis_pool.llen = AsyncMock(return_value=10)

        # Mock job statistics and failures
        with (
            patch.object(
                service, "_get_job_statistics", new_callable=AsyncMock
            ) as mock_stats,
            patch.object(
                service, "_get_recent_failures", new_callable=AsyncMock
            ) as mock_failures,
            patch("aiohttp.ClientSession") as mock_session_class,
        ):
            mock_stats.return_value = {
                "total_jobs": 100,
                "completed_jobs": 95,
                "failed_jobs": 3,
                "cancelled_jobs": 2,
                "running_jobs": 2,
                "queued_jobs": 5,
                "retry_count": 0,
            }
            mock_failures.return_value = []

            # Mock aiohttp session
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            # Get overall health
            health = await service.get_overall_health()

            # Verify queue metrics are included
            assert "queue_metrics" in health
            assert health["queue_metrics"]["queue_depth"] == 10
            assert health["queue_metrics"]["queued_jobs"] == 5
            assert health["queue_metrics"]["running_jobs"] == 2

    @pytest.mark.asyncio
    async def test_get_overall_health_includes_job_statistics(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test that overall health includes job statistics."""
        # Mock Redis responses
        mock_redis_pool.ping = AsyncMock(return_value=True)
        mock_redis_pool.info = AsyncMock(
            return_value={
                "used_memory_human": "1M",
                "connected_clients": 5,
            }
        )
        mock_redis_pool.llen = AsyncMock(return_value=0)

        # Mock job statistics and failures
        with (
            patch.object(
                service, "_get_job_statistics", new_callable=AsyncMock
            ) as mock_stats,
            patch.object(
                service, "_get_recent_failures", new_callable=AsyncMock
            ) as mock_failures,
            patch("aiohttp.ClientSession") as mock_session_class,
        ):
            mock_stats.return_value = {
                "total_jobs": 100,
                "completed_jobs": 90,
                "failed_jobs": 8,
                "cancelled_jobs": 2,
                "running_jobs": 0,
                "queued_jobs": 0,
                "retry_count": 3,
            }
            mock_failures.return_value = []

            # Mock aiohttp session
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            # Get overall health
            health = await service.get_overall_health()

            # Verify job statistics are included
            assert "job_statistics" in health
            assert health["job_statistics"]["total_jobs_24h"] == 100
            assert health["job_statistics"]["completed_jobs_24h"] == 90
            assert health["job_statistics"]["failed_jobs_24h"] == 8
            assert health["job_statistics"]["cancelled_jobs_24h"] == 2
            assert health["job_statistics"]["retry_count_24h"] == 3

    @pytest.mark.asyncio
    async def test_get_overall_health_includes_recent_failures(
        self, service: IntegrationHealthService, mock_redis_pool: AsyncMock
    ):
        """Test that overall health includes recent failures."""
        # Mock Redis responses
        mock_redis_pool.ping = AsyncMock(return_value=True)
        mock_redis_pool.info = AsyncMock(
            return_value={
                "used_memory_human": "1M",
                "connected_clients": 5,
            }
        )
        mock_redis_pool.llen = AsyncMock(return_value=0)

        # Mock job statistics and failures
        from datetime import UTC, datetime

        with (
            patch.object(
                service, "_get_job_statistics", new_callable=AsyncMock
            ) as mock_stats,
            patch.object(
                service, "_get_recent_failures", new_callable=AsyncMock
            ) as mock_failures,
            patch("aiohttp.ClientSession") as mock_session_class,
        ):
            mock_stats.return_value = {
                "total_jobs": 10,
                "completed_jobs": 8,
                "failed_jobs": 2,
                "cancelled_jobs": 0,
                "running_jobs": 0,
                "queued_jobs": 0,
                "retry_count": 0,
            }
            mock_failures.return_value = [
                {
                    "job_id": "job-1",
                    "user_id": "user-1",
                    "sync_type": "smart",
                    "error_message": "Connection timeout",
                    "created_at": datetime.now(UTC).isoformat(),
                    "failed_at": datetime.now(UTC).isoformat(),
                },
                {
                    "job_id": "job-2",
                    "user_id": "user-2",
                    "sync_type": "full",
                    "error_message": "API rate limit exceeded",
                    "created_at": datetime.now(UTC).isoformat(),
                    "failed_at": datetime.now(UTC).isoformat(),
                },
            ]

            # Mock aiohttp session
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            # Get overall health
            health = await service.get_overall_health()

            # Verify recent failures are included
            assert "recent_failures" in health
            assert len(health["recent_failures"]) == 2
            assert health["recent_failures"][0]["job_id"] == "job-1"
            assert health["recent_failures"][0]["error_message"] == "Connection timeout"
            assert health["recent_failures"][1]["job_id"] == "job-2"
            assert (
                health["recent_failures"][1]["error_message"]
                == "API rate limit exceeded"
            )
