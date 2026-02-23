"""
Health Service for monitoring integration services.

Provides health checks for Redis, workers, and external APIs
to ensure the integration system is functioning properly.
"""

from datetime import UTC, datetime
from typing import Any

import aiohttp
from arq.connections import ArqRedis
from core_shared.logging import get_logger
from core_shared.repositories import SyncJobRepository

from app.core.integrations.database import IntegrationDatabaseManager

logger = get_logger(__name__)

# ARQ queue name for Google Contacts worker
ARQ_QUEUE_NAME = "google_contacts"


class IntegrationHealthService:
    """
    Service for monitoring integration service health.

    Provides comprehensive health checks for all integration
    components including Redis, workers, and external APIs.
    """

    def __init__(self, redis_pool: ArqRedis, db_manager: IntegrationDatabaseManager):
        """
        Initialize the health service.

        Args:
            redis_pool: ARQ Redis connection pool for health checks
            db_manager: Database manager for job statistics
        """
        self.redis_pool = redis_pool
        self.db_manager = db_manager

    async def get_overall_health(self) -> dict[str, Any]:
        """
        Get the overall health status of all integration services.

        Returns:
            Dictionary with comprehensive health information including:
            - status: Overall health status
            - services: Health of individual services
            - queue_metrics: Queue depth and statistics
            - job_statistics: Recent job statistics (failures, retries, etc.)
            - recent_failures: List of recent failed jobs
        """
        logger.debug("Performing overall health check")

        # Check individual services
        redis_health = await self._check_redis_health()
        worker_health = await self._check_worker_health()
        external_api_health = await self._check_external_api_health()

        # Get job statistics
        job_stats = await self._get_job_statistics()
        recent_failures = await self._get_recent_failures()

        # Determine overall status
        all_services = [redis_health, worker_health, external_api_health]
        overall_status = "healthy"

        for service in all_services:
            if service["status"] == "unhealthy":
                overall_status = "unhealthy"
                break
            elif service["status"] == "degraded":
                overall_status = "degraded"

        # Degrade status if there are many recent failures
        if job_stats.get("failed_jobs", 0) > 5:
            overall_status = (
                "degraded" if overall_status == "healthy" else overall_status
            )

        return {
            "status": overall_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "services": {
                "redis": redis_health,
                "google_contacts_worker": worker_health,
                "google_api": external_api_health,
            },
            "queue_metrics": {
                "queue_depth": redis_health.get("queue_length", 0),
                "queued_jobs": job_stats.get("queued_jobs", 0),
                "running_jobs": job_stats.get("running_jobs", 0),
            },
            "job_statistics": {
                "total_jobs_24h": job_stats.get("total_jobs", 0),
                "completed_jobs_24h": job_stats.get("completed_jobs", 0),
                "failed_jobs_24h": job_stats.get("failed_jobs", 0),
                "cancelled_jobs_24h": job_stats.get("cancelled_jobs", 0),
                "retry_count_24h": job_stats.get("retry_count", 0),
            },
            "recent_failures": recent_failures,
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

            # Check queue length using ARQ's API
            queued_jobs = await self.redis_pool.queued_jobs(queue_name=ARQ_QUEUE_NAME)
            queue_length = len(queued_jobs)

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
            # Use ARQ's API to get queued jobs
            queued_jobs = await self.redis_pool.queued_jobs(queue_name=ARQ_QUEUE_NAME)
            recent_jobs = len(queued_jobs)

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
            # Use ARQ's API to get queued jobs
            queued_jobs = await self.redis_pool.queued_jobs(queue_name=ARQ_QUEUE_NAME)
            return len(queued_jobs)

        except Exception:
            return 0

    async def _get_job_statistics(self) -> dict[str, Any]:
        """Get job statistics from the database."""
        try:
            async with self.db_manager.get_session() as session:
                conn = await session.connection()
                repo = SyncJobRepository(conn)
                stats = await repo.get_job_statistics(
                    integration_source="google_contacts", hours=24
                )
                return stats
        except Exception as e:
            logger.error("Failed to get job statistics", error=str(e))
            return {
                "total_jobs": 0,
                "completed_jobs": 0,
                "failed_jobs": 0,
                "cancelled_jobs": 0,
                "running_jobs": 0,
                "queued_jobs": 0,
                "retry_count": 0,
            }

    async def _get_recent_failures(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get recent failed jobs."""
        try:
            async with self.db_manager.get_session() as session:
                conn = await session.connection()
                repo = SyncJobRepository(conn)
                failures = await repo.get_recent_failures(
                    integration_source="google_contacts", hours=24, limit=limit
                )

                # Convert to dict format for API response
                return [
                    {
                        "job_id": job.job_id,
                        "user_id": job.user_id,
                        "sync_type": job.sync_type,
                        "error_message": job.error_message,
                        "created_at": job.created_at.isoformat()
                        if job.created_at
                        else None,
                        "failed_at": (
                            job.completed_at.isoformat() if job.completed_at else None
                        ),
                    }
                    for job in failures
                ]
        except Exception as e:
            logger.error("Failed to get recent failures", error=str(e))
            return []

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
