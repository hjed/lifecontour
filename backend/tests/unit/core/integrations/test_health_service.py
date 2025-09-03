"""
Unit tests for IntegrationHealthService.

Tests the health monitoring functionality for integration services
including Redis, workers, and external APIs.
"""

from unittest.mock import AsyncMock

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
    def service(self, mock_redis_pool: AsyncMock) -> IntegrationHealthService:
        """Create IntegrationHealthService instance."""
        return IntegrationHealthService(redis_pool=mock_redis_pool)

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
        mock_redis_pool.info = AsyncMock(return_value={
            "used_memory_human": "2.1M",
            "connected_clients": 5,
        })
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
        assert health["recent_jobs"] == 1
        assert "last_seen" in health
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
        # Check external API health (currently returns mock data)
        health = await service._check_external_api_health()

        # Verify health response
        assert health["status"] == "healthy"
        assert health["rate_limit_remaining"] == "90%"
        assert "last_successful_call" in health
        assert health["average_response_time_ms"] == 150
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
        assert health["recent_jobs"] == 0

    @pytest.mark.asyncio
    async def test_check_service_connectivity_google_api(
        self, service: IntegrationHealthService
    ):
        """Test service connectivity check for Google API."""
        # Check Google API connectivity
        health = await service.check_service_connectivity("google_api")

        # Verify it returns Google API health
        assert health["status"] == "healthy"
        assert health["rate_limit_remaining"] == "90%"

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
