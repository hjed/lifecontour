"""
Health Service for monitoring integration services.

Provides health checks for Redis, workers, and external APIs
to ensure the integration system is functioning properly.
"""

from datetime import UTC, datetime
from typing import Any

import aiohttp
import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()


class IntegrationHealthService:
    """
    Service for monitoring integration service health.

    Provides comprehensive health checks for all integration
    components including Redis, workers, and external APIs.
    """

    def __init__(self, redis_pool: Redis):
        """
        Initialize the health service.

        Args:
            redis_pool: Redis connection pool for health checks
        """
        self.redis_pool = redis_pool

    async def get_overall_health(self) -> dict[str, Any]:
        """
        Get the overall health status of all integration services.

        Returns:
            Dictionary with comprehensive health information
        """
        logger.debug("Performing overall health check")

        # Check individual services
        redis_health = await self._check_redis_health()
        worker_health = await self._check_worker_health()
        external_api_health = await self._check_external_api_health()

        # Determine overall status
        all_services = [redis_health, worker_health, external_api_health]
        overall_status = "healthy"

        for service in all_services:
            if service["status"] == "unhealthy":
                overall_status = "unhealthy"
                break
            elif service["status"] == "degraded":
                overall_status = "degraded"

        return {
            "status": overall_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "services": {
                "redis": redis_health,
                "google_contacts_worker": worker_health,
                "google_api": external_api_health,
            },
            "version": "1.0.0",
        }

    async def _check_redis_health(self) -> dict[str, Any]:
        """Check Redis health and connectivity."""
        try:
            # Test basic connectivity
            start_time = datetime.now(UTC)
            await self.redis_pool.ping()
            end_time = datetime.now(UTC)

            response_time_ms = (end_time - start_time).total_seconds() * 1000

            # Get Redis info
            info = await self.redis_pool.info()
            memory_usage = info.get("used_memory_human", "unknown")
            connected_clients = info.get("connected_clients", 0)

            # Check queue length
            queue_length_result = await self.redis_pool.llen("arq:queue")  # type: ignore
            queue_length = (
                int(queue_length_result) if queue_length_result is not None else 0
            )

            return {
                "status": "healthy",
                "response_time_ms": round(response_time_ms, 2),
                "memory_usage": memory_usage,
                "connected_clients": connected_clients,
                "queue_length": queue_length,
                "last_checked": datetime.now(UTC).isoformat(),
            }

        except Exception as e:
            logger.error("Redis health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e),
                "last_checked": datetime.now(UTC).isoformat(),
            }

    async def _check_worker_health(self) -> dict[str, Any]:
        """Check Google Contacts worker health."""
        try:
            # Check for recent worker activity by looking at job processing
            # This is a simplified check - in production you might want to
            # implement worker heartbeats or more sophisticated monitoring

            # Check if there are any recent jobs in the queue or completed
            # This will raise an exception if Redis is not accessible
            recent_jobs_result = await self.redis_pool.llen("arq:queue")  # type: ignore
            recent_jobs = (
                int(recent_jobs_result) if recent_jobs_result is not None else 0
            )

            # For now, assume worker is healthy if Redis is accessible
            # In a real implementation, you might check:
            # - Worker heartbeat timestamps
            # - Recent job completion rates
            # - Worker process status

            # Check for worker activity indicators
            # In a production system, workers would set heartbeat keys
            worker_status = "healthy" if recent_jobs >= 0 else "unknown"

            return {
                "status": worker_status,
                "queue_length": recent_jobs,
                "worker_version": "1.0.0",
                "last_checked": datetime.now(UTC).isoformat(),
                "note": "Worker health based on queue accessibility - implement heartbeat for better monitoring",
            }

        except Exception as e:
            logger.error("Worker health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e),
                "last_checked": datetime.now(UTC).isoformat(),
            }

    async def _check_external_api_health(self) -> dict[str, Any]:
        """Check external API health (Google APIs)."""
        try:
            # Test Google API connectivity with a simple request
            start_time = datetime.now(UTC)

            async with aiohttp.ClientSession() as session:
                # Test Google's OAuth2 discovery endpoint (public, no auth required)
                async with session.get(
                    "https://accounts.google.com/.well-known/openid-configuration",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        end_time = datetime.now(UTC)
                        response_time_ms = (
                            end_time - start_time
                        ).total_seconds() * 1000

                        return {
                            "status": "healthy",
                            "response_time_ms": round(response_time_ms, 2),
                            "last_successful_call": end_time.isoformat(),
                            "endpoint_tested": "Google OAuth2 discovery",
                            "last_checked": datetime.now(UTC).isoformat(),
                        }
                    else:
                        return {
                            "status": "degraded",
                            "error": f"Google API returned status {response.status}",
                            "last_checked": datetime.now(UTC).isoformat(),
                        }

        except TimeoutError:
            logger.error("External API health check timed out")
            return {
                "status": "unhealthy",
                "error": "Google API request timed out",
                "last_checked": datetime.now(UTC).isoformat(),
            }
        except aiohttp.ClientError as e:
            logger.error("External API health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": f"Google API connection failed: {str(e)}",
                "last_checked": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.error("External API health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e),
                "last_checked": datetime.now(UTC).isoformat(),
            }

    async def _get_recent_job_count(self) -> int:
        """Get count of recent jobs for worker health assessment."""
        try:
            # This is a simplified implementation
            # In production, you might track job metrics in Redis
            # or use ARQ's built-in job tracking

            # For now, just return the current queue length as a proxy
            queue_length_result = await self.redis_pool.llen("arq:queue")  # type: ignore
            return int(queue_length_result) if queue_length_result is not None else 0

        except Exception:
            return 0

    async def check_service_connectivity(self, service_name: str) -> dict[str, Any]:
        """
        Check connectivity to a specific service.

        Args:
            service_name: Name of the service to check

        Returns:
            Service-specific health information
        """
        if service_name == "redis":
            return await self._check_redis_health()
        elif service_name == "worker":
            return await self._check_worker_health()
        elif service_name == "google_api":
            return await self._check_external_api_health()
        else:
            return {
                "status": "unknown",
                "error": f"Unknown service: {service_name}",
                "last_checked": datetime.now(UTC).isoformat(),
            }
