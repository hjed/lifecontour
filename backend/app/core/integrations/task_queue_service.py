"""
Task Queue Service for managing ARQ background jobs.

Provides operations for enqueueing tasks, checking job status,
and managing the ARQ task queue for integration workers.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job, JobDef, JobStatus
from redis.asyncio import Redis

logger = structlog.get_logger()


class TaskQueueService:
    """
    Service for managing ARQ task queue operations.

    Handles job enqueueing, status checking, and queue management
    for integration workers.
    """

    def __init__(self, redis_pool: Redis, redis_settings: RedisSettings):
        """
        Initialize the task queue service.

        Args:
            redis_pool: Redis connection pool
            redis_settings: Redis settings for ARQ
        """
        self.redis_pool = redis_pool
        self.redis_settings = redis_settings

    async def enqueue_google_contacts_sync(
        self, google_account_email: str, user_id: int, sync_type: str = "smart"
    ) -> str:
        """
        Enqueue a Google Contacts sync job.

        Args:
            google_account_email: Google account email to sync
            user_id: ID of the user requesting the sync
            sync_type: Type of sync ('full', 'incremental', or 'smart')

        Returns:
            Job ID for tracking the job status

        Raises:
            Exception: If job enqueueing fails
        """
        logger.info(
            "Enqueueing Google Contacts sync job",
            google_account_email=google_account_email,
            user_id=user_id,
            sync_type=sync_type,
        )

        try:
            # Create ARQ pool for job enqueueing
            pool = await create_pool(self.redis_settings)

            # Enqueue the sync job
            job = await pool.enqueue_job(
                "sync_google_contacts",
                google_account_email,
                user_id,
                sync_type,
                _job_timeout=300,  # 5 minutes timeout
                _defer_until=None,  # Run immediately
            )

            await pool.close()

            if not job:
                raise Exception("Failed to enqueue job - no job returned")

            job_id = job.job_id
            logger.info(
                "Successfully enqueued Google Contacts sync job",
                job_id=job_id,
                google_account_email=google_account_email,
                user_id=user_id,
                sync_type=sync_type,
            )

            # Store user-job association for security
            await self._store_user_job_association(user_id, job_id)

            return job_id

        except Exception as e:
            logger.error(
                "Failed to enqueue Google Contacts sync job",
                google_account_email=google_account_email,
                user_id=user_id,
                sync_type=sync_type,
                error=str(e),
            )
            raise

    async def get_job_status(self, job_id: str, user_id: int) -> dict[str, Any]:
        """
        Get the status of a specific job.

        Args:
            job_id: Job ID to check
            user_id: ID of the user requesting the status

        Returns:
            Dictionary with job status information

        Raises:
            Exception: If job status check fails or user doesn't own the job
        """
        logger.debug("Checking job status", job_id=job_id, user_id=user_id)

        # Security check: Verify user owns this job
        if not await self._verify_user_job_ownership(user_id, job_id):
            raise Exception(f"Job {job_id} not found or access denied")

        try:
            # Create ARQ pool for job status checking
            pool = await create_pool(self.redis_settings)

            # Get job information
            job = Job(job_id, redis=pool)
            job_info: JobDef | None = await job.info()

            await pool.close()

            if not job_info:
                return {
                    "job_id": job_id,
                    "status": "not_found",
                    "message": "Job not found",
                    "created_at": None,
                    "started_at": None,
                    "completed_at": None,
                    "result": None,
                    "error": None,
                }

            # Map ARQ job status to our API status
            status_mapping = {
                JobStatus.deferred: "queued",
                JobStatus.queued: "queued",
                JobStatus.in_progress: "running",
                JobStatus.complete: "completed",
                JobStatus.not_found: "not_found",
            }

            api_status = status_mapping.get(job_info.job_status, "unknown")  # type: ignore

            # Format timestamps
            created_at = (
                job_info.enqueue_time.isoformat() if job_info.enqueue_time else None
            )
            started_at = (
                job_info.start_time.isoformat() if job_info.start_time else None  # type: ignore
            )
            completed_at = (
                job_info.finish_time.isoformat() if job_info.finish_time else None  # type: ignore
            )

            result = {
                "job_id": job_id,
                "status": api_status,
                "message": self._get_status_message(api_status, job_info),
                "created_at": created_at,
                "started_at": started_at,
                "completed_at": completed_at,
                "result": job_info.result,  # type: ignore
                "error": str(job_info.result)  # type: ignore
                if job_info.job_status == JobStatus.not_found and job_info.result  # type: ignore
                else None,
            }

            logger.debug(
                "Retrieved job status",
                job_id=job_id,
                status=api_status,
                arq_status=job_info.job_status,  # type: ignore
            )

            return result

        except Exception as e:
            logger.error("Failed to get job status", job_id=job_id, error=str(e))
            raise

    async def get_queue_health(self) -> dict[str, Any]:
        """
        Get the health status of the task queue.

        Returns:
            Dictionary with queue health information
        """
        logger.debug("Checking queue health")

        try:
            # Check Redis connectivity
            await self.redis_pool.ping()

            # Get queue statistics
            queue_length_result = await self.redis_pool.llen("arq:queue")  # type: ignore
            queue_length = (
                int(queue_length_result) if queue_length_result is not None else 0
            )

            # Check if Redis is responsive
            start_time = datetime.now(UTC)
            await self.redis_pool.ping()
            end_time = datetime.now(UTC)
            response_time_ms = (end_time - start_time).total_seconds() * 1000

            return {
                "status": "healthy",
                "redis_connected": True,
                "queue_length": queue_length,
                "response_time_ms": round(response_time_ms, 2),
                "checked_at": datetime.now(UTC).isoformat(),
            }

        except Exception as e:
            logger.error("Queue health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "redis_connected": False,
                "queue_length": None,
                "response_time_ms": None,
                "error": str(e),
                "checked_at": datetime.now(UTC).isoformat(),
            }

    def _get_status_message(self, status: str, job_info: Any) -> str:
        """Get a human-readable status message."""
        if status == "queued":
            return "Job is queued and waiting to be processed"
        elif status == "running":
            return "Job is currently being processed"
        elif status == "completed":
            if job_info.result and isinstance(job_info.result, dict):
                if job_info.result.get("status") == "success":
                    return "Job completed successfully"
                else:
                    return f"Job completed with status: {job_info.result.get('status', 'unknown')}"
            return "Job completed"
        elif status == "not_found":
            return "Job not found or expired"
        else:
            return f"Job status: {status}"

    async def _store_user_job_association(self, user_id: int, job_id: str) -> None:
        """
        Store user-job association for security checks.

        Args:
            user_id: User ID
            job_id: Job ID
        """
        try:
            # Store association with 24-hour expiration
            key = f"user_jobs:{user_id}"
            await self.redis_pool.hset(key, job_id, "enqueued")  # type: ignore
            await self.redis_pool.expire(key, 86400)  # 24 hours
            logger.debug("Stored user-job association", user_id=user_id, job_id=job_id)
        except Exception as e:
            logger.warning(
                "Failed to store user-job association",
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            # Don't raise - this is a security enhancement, not critical for functionality

    async def _verify_user_job_ownership(self, user_id: int, job_id: str) -> bool:
        """
        Verify that a user owns a specific job.

        Args:
            user_id: User ID
            job_id: Job ID

        Returns:
            True if user owns the job, False otherwise
        """
        try:
            key = f"user_jobs:{user_id}"
            result = await self.redis_pool.hexists(key, job_id)  # type: ignore
            owns_job = bool(result) if result is not None else False
            logger.debug(
                "Verified user-job ownership",
                user_id=user_id,
                job_id=job_id,
                owns_job=owns_job,
            )
            return owns_job
        except Exception as e:
            logger.warning(
                "Failed to verify user-job ownership",
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            # On error, deny access for security
            return False
