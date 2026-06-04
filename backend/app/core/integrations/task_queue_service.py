"""
Task Queue Service for managing ARQ background jobs.

Provides operations for enqueueing tasks, checking job status,
and managing the ARQ task queue for integration workers.
"""

from datetime import UTC, datetime
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobDef, JobStatus
from core_shared.integration_constants import (
    GOOGLE_ARQ_QUEUE_NAME as ARQ_QUEUE_NAME,
)
from core_shared.logging import get_logger
from core_shared.metrics import queue_depth
from core_shared.repositories import SyncJobRepository

from app.core.integrations.database import IntegrationDatabaseManager
from app.core.integrations.exceptions import JobEnqueueError, JobNotFoundException
from app.infrastructure.config import Settings

logger = get_logger(__name__)


class TaskQueueService:
    """
    Service for managing ARQ task queue operations.

    Handles job enqueueing, status checking, and queue management
    for integration workers.
    """

    def __init__(
        self,
        redis_settings: RedisSettings,
        settings: Settings,
        db_manager: IntegrationDatabaseManager,
        redis_pool: ArqRedis | None = None,
        worker_type: str = "google",
    ):
        """
        Initialize the task queue service.

        Args:
            redis_pool: ARQ Redis connection pool
            redis_settings: Redis settings for ARQ
            settings: Application settings
            db_manager: Database manager for persisting sync jobs
            worker_type: Type of worker for metrics labeling (default: "google")
        """
        self.redis_pool = redis_pool
        self.redis_settings = redis_settings
        self.settings = settings
        self.db_manager = db_manager
        self.worker_type = worker_type
        self._arq_pool: ArqRedis | None = None

    async def _get_arq_pool(self) -> ArqRedis:
        """Get or create the ARQ pool for job operations."""
        if self._arq_pool is None:
            if self.redis_pool is not None:
                self._arq_pool = self.redis_pool
            else:
                self._arq_pool = await create_pool(self.redis_settings)
        return self._arq_pool

    async def close(self) -> None:
        """Close the ARQ pool connection."""
        if self._arq_pool is not None and self._arq_pool is not self.redis_pool:
            await self._arq_pool.close()
            self._arq_pool = None

    async def enqueue_google_sync(
        self, google_account_email: str, user_id: str | int, sync_type: str = "smart"
    ) -> str:
        """
        Enqueue a Google Contacts sync job.

        Args:
            google_account_email: Google account email to sync
            user_id: ID of the user requesting the sync (string or integer)
            sync_type: Type of sync ('full', 'incremental', or 'smart')

        Returns:
            Job ID for tracking the job status

        Raises:
            JobEnqueueError: If job enqueueing fails
            ConnectionError: If Redis connection fails
        """
        logger.info(
            "Enqueueing Google Contacts sync job",
            google_account_email=google_account_email,
            user_id=user_id,
            sync_type=sync_type,
        )

        try:
            # Get reusable ARQ pool for job enqueueing
            pool = await self._get_arq_pool()

            from opentelemetry.propagate import inject

            carrier: dict[str, str] = {}
            try:
                inject(carrier)
            except Exception:  # noqa: BLE001
                pass

            # Enqueue the sync job
            job = await pool.enqueue_job(
                "sync_google_contacts",
                google_account_email,
                user_id,
                sync_type,
                otel_carrier=carrier,
                _defer_until=None,  # Run immediately
                _queue_name=ARQ_QUEUE_NAME,
            )

            if not job:
                raise JobEnqueueError(
                    message="Failed to enqueue job - no job returned",
                    integration_source="google",
                    reason="ARQ pool returned None",
                )

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

            # Persist job to database for history tracking
            async with self.db_manager.get_session() as session:
                async with session.begin():
                    conn = await session.connection()
                    repo = SyncJobRepository(conn)
                    await repo.create(
                        job_id=job_id,
                        user_id=str(user_id),
                        integration_source="google",
                        sync_type=sync_type,
                        status="queued",
                    )

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

    async def enqueue_calendar_sync(
        self, google_account_email: str, user_id: str | int, sync_type: str = "smart"
    ) -> str:
        """
        Enqueue a Google Calendar sync job.

        Args:
            google_account_email: Google account email to sync
            user_id: ID of the user requesting the sync (string or integer)
            sync_type: Type of sync ('full', 'incremental', or 'smart')

        Returns:
            Job ID for tracking the job status

        Raises:
            JobEnqueueError: If job enqueueing fails
            ConnectionError: If Redis connection fails
        """
        logger.info(
            "Enqueueing Google Calendar sync job",
            google_account_email=google_account_email,
            user_id=user_id,
            sync_type=sync_type,
        )

        try:
            pool = await self._get_arq_pool()

            from opentelemetry.propagate import inject

            carrier: dict[str, str] = {}
            try:
                inject(carrier)
            except Exception:  # noqa: BLE001
                pass

            job = await pool.enqueue_job(
                "sync_calendar_events",
                google_account_email,
                user_id,
                sync_type,
                otel_carrier=carrier,
                _defer_until=None,
                _queue_name=ARQ_QUEUE_NAME,
            )

            if not job:
                raise JobEnqueueError(
                    message="Failed to enqueue calendar sync job - no job returned",
                    integration_source="google",
                    reason="ARQ pool returned None",
                )

            job_id = job.job_id
            logger.info(
                "Successfully enqueued Google Calendar sync job",
                job_id=job_id,
                google_account_email=google_account_email,
                user_id=user_id,
                sync_type=sync_type,
            )

            # Store user-job association for security
            await self._store_user_job_association(user_id, job_id)

            # Persist job to database for history tracking
            async with self.db_manager.get_session() as session:
                async with session.begin():
                    conn = await session.connection()
                    repo = SyncJobRepository(conn)
                    await repo.create(
                        job_id=job_id,
                        user_id=str(user_id),
                        integration_source="google",
                        sync_type=sync_type,
                        status="queued",
                    )

            return job_id

        except Exception as e:
            logger.error(
                "Failed to enqueue Google Calendar sync job",
                google_account_email=google_account_email,
                user_id=user_id,
                sync_type=sync_type,
                error=str(e),
            )
            raise

    async def enqueue_strava_sync(
        self, user_id: str | int, sync_type: str = "full"
    ) -> str:
        """
        Enqueue a Strava activity sync job.

        Args:
            user_id: ID of the user requesting the sync (string or integer)
            sync_type: Type of sync ('full' or 'smart')

        Returns:
            Job ID for tracking the job status

        Raises:
            JobEnqueueError: If job enqueueing fails
            ConnectionError: If Redis connection fails
        """
        from core_shared.integration_constants import STRAVA_ARQ_QUEUE_NAME

        logger.info(
            "Enqueueing Strava activity sync job",
            user_id=user_id,
            sync_type=sync_type,
        )

        try:
            pool = await self._get_arq_pool()

            from opentelemetry.propagate import inject

            carrier: dict[str, str] = {}
            try:
                inject(carrier)
            except Exception:  # noqa: BLE001
                pass

            job = await pool.enqueue_job(
                "sync_strava_activities",
                str(user_id),
                sync_type,
                otel_carrier=carrier,
                _defer_until=None,
                _queue_name=STRAVA_ARQ_QUEUE_NAME,
            )

            if not job:
                raise JobEnqueueError(
                    message="Failed to enqueue Strava sync job - no job returned",
                    integration_source="strava",
                    reason="ARQ pool returned None",
                )

            job_id = job.job_id
            logger.info(
                "Successfully enqueued Strava activity sync job",
                job_id=job_id,
                user_id=user_id,
                sync_type=sync_type,
            )

            # Store user-job association for security
            await self._store_user_job_association(user_id, job_id)

            # Persist job to database for history tracking
            async with self.db_manager.get_session() as session:
                async with session.begin():
                    conn = await session.connection()
                    repo = SyncJobRepository(conn)
                    await repo.create(
                        job_id=job_id,
                        user_id=str(user_id),
                        integration_source="strava",
                        sync_type=sync_type,
                        status="queued",
                    )

            return job_id

        except Exception as e:
            logger.error(
                "Failed to enqueue Strava activity sync job",
                user_id=user_id,
                sync_type=sync_type,
                error=str(e),
            )
            raise

    async def enqueue_snipeit_sync(
        self, user_id: str | int, sync_type: str = "full"
    ) -> str:
        """
        Enqueue a Snipe-IT sync job.

        Args:
            user_id: ID of the user requesting the sync (string or integer)
            sync_type: Type of sync ('full' or 'smart')

        Returns:
            Job ID for tracking the job status

        Raises:
            JobEnqueueError: If job enqueueing fails
            ConnectionError: If Redis connection fails
        """
        from core_shared.integration_constants import SNIPEIT_ARQ_QUEUE_NAME

        logger.info(
            "Enqueueing Snipe-IT sync job",
            user_id=user_id,
            sync_type=sync_type,
        )

        try:
            pool = await self._get_arq_pool()

            from opentelemetry.propagate import inject

            carrier: dict[str, str] = {}
            try:
                inject(carrier)
            except Exception:  # noqa: BLE001
                pass

            job = await pool.enqueue_job(
                "sync_snipeit_assets",
                str(user_id),
                sync_type,
                otel_carrier=carrier,
                _defer_until=None,
                _queue_name=SNIPEIT_ARQ_QUEUE_NAME,
            )

            if not job:
                raise JobEnqueueError(
                    message="Failed to enqueue Snipe-IT sync job - no job returned",
                    integration_source="snipeit",
                    reason="ARQ pool returned None",
                )

            job_id = job.job_id
            logger.info(
                "Successfully enqueued Snipe-IT sync job",
                job_id=job_id,
                user_id=user_id,
                sync_type=sync_type,
            )

            # Store user-job association for security
            await self._store_user_job_association(user_id, job_id)

            # Persist job to database for history tracking
            async with self.db_manager.get_session() as session:
                async with session.begin():
                    conn = await session.connection()
                    repo = SyncJobRepository(conn)
                    await repo.create(
                        job_id=job_id,
                        user_id=str(user_id),
                        integration_source="snipeit",
                        sync_type=sync_type,
                        status="queued",
                    )

            return job_id

        except Exception as e:
            logger.error(
                "Failed to enqueue Snipe-IT sync job",
                user_id=user_id,
                sync_type=sync_type,
                error=str(e),
            )
            raise

    async def enqueue_snipeit_maintenance_sync(
        self, user_id: str | int, sync_type: str = "full"
    ) -> str:
        """
        Enqueue a Snipe-IT maintenance sync job.

        Args:
            user_id: ID of the user requesting the sync (string or integer)
            sync_type: Type of sync ('full' or 'smart')

        Returns:
            Job ID for tracking the job status

        Raises:
            JobEnqueueError: If job enqueueing fails
            ConnectionError: If Redis connection fails
        """
        from core_shared.integration_constants import SNIPEIT_ARQ_QUEUE_NAME

        logger.info(
            "Enqueueing Snipe-IT maintenance sync job",
            user_id=user_id,
            sync_type=sync_type,
        )

        try:
            pool = await self._get_arq_pool()

            from opentelemetry.propagate import inject

            carrier: dict[str, str] = {}
            try:
                inject(carrier)
            except Exception:  # noqa: BLE001
                pass

            job = await pool.enqueue_job(
                "sync_snipeit_maintenances",
                str(user_id),
                sync_type,
                otel_carrier=carrier,
                _defer_until=None,
                _queue_name=SNIPEIT_ARQ_QUEUE_NAME,
            )

            if not job:
                raise JobEnqueueError(
                    message="Failed to enqueue Snipe-IT maintenance sync job - no job returned",
                    integration_source="snipeit",
                    reason="ARQ pool returned None",
                )

            job_id = job.job_id
            logger.info(
                "Successfully enqueued Snipe-IT maintenance sync job",
                job_id=job_id,
                user_id=user_id,
                sync_type=sync_type,
            )

            # Store user-job association for security
            await self._store_user_job_association(user_id, job_id)

            # Persist job to database for history tracking
            async with self.db_manager.get_session() as session:
                async with session.begin():
                    conn = await session.connection()
                    repo = SyncJobRepository(conn)
                    await repo.create(
                        job_id=job_id,
                        user_id=str(user_id),
                        integration_source="snipeit",
                        sync_type=sync_type,
                        status="queued",
                    )

            return job_id

        except Exception as e:
            logger.error(
                "Failed to enqueue Snipe-IT maintenance sync job",
                user_id=user_id,
                sync_type=sync_type,
                error=str(e),
            )
            raise

    async def get_job_status(self, job_id: str, user_id: str | int) -> dict[str, Any]:
        """
        Get the status of a specific job.

        Args:
            job_id: Job ID to check
            user_id: ID of the user requesting the status (string or integer)

        Returns:
            Dictionary with job status information

        Raises:
            JobNotFoundException: If job is not found or user doesn't own the job
            ConnectionError: If Redis connection fails
        """
        logger.debug("Checking job status", job_id=job_id, user_id=user_id)

        # Security check: Verify user owns this job
        if not await self._verify_user_job_ownership(user_id, job_id):
            raise JobNotFoundException(
                job_id=job_id, message="Job not found or access denied"
            )

        try:
            # Get reusable ARQ pool for job status checking
            pool = await self._get_arq_pool()

            # Get job information
            job = Job(job_id, redis=pool)
            job_info: JobDef | None = await job.info()

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

            # Get job result from the Job object
            job_result = await job.result()

            # Check if job failed by examining the result
            if (
                api_status == "completed"
                and job_result
                and isinstance(job_result, dict)
                and job_result.get("status") == "error"
            ):
                api_status = "failed"

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

            # Extract error information for failed jobs
            error_message = None
            if api_status == "failed" and job_result and isinstance(job_result, dict):
                error_message = job_result.get("error", "Job failed with unknown error")
            elif api_status == "not_found":
                error_message = "Job not found or expired"

            result = {
                "job_id": job_id,
                "status": api_status,
                "message": self._get_status_message(api_status, job_info),
                "created_at": created_at,
                "started_at": started_at,
                "completed_at": completed_at,
                "result": job_result,
                "error": error_message,
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

    async def cancel_job(self, job_id: str, user_id: str | int) -> dict[str, Any]:
        """
        Cancel a running or queued job.

        Args:
            job_id: ARQ job ID to cancel
            user_id: User ID requesting cancellation (for authorization)

        Returns:
            Dictionary with cancellation status

        Raises:
            JobNotFoundException: If job is not found or user is not authorized
            PermissionError: If user doesn't own the job
        """
        logger.info("Cancelling job", job_id=job_id, user_id=user_id)

        try:
            # Verify user owns this job
            if not await self._verify_user_job_ownership(user_id, job_id):
                raise PermissionError(
                    f"User {user_id} is not authorized to cancel job {job_id}"
                )

            # Update job status to cancelled in database
            async with self.db_manager.get_session() as session:
                conn = await session.connection()
                repo = SyncJobRepository(conn)
                sync_job = await repo.update_status(
                    job_id=job_id,
                    status="cancelled",
                    completed_at=datetime.now(UTC),
                    progress=None,  # Clear progress on cancellation
                )
                await session.commit()

                if not sync_job:
                    raise JobNotFoundException(
                        job_id=job_id, message="Job not found in database"
                    )

            # Note: ARQ doesn't support job cancellation directly
            # The worker will check the database status and stop processing
            logger.info(
                "Job marked as cancelled",
                job_id=job_id,
                user_id=user_id,
            )

            return {
                "job_id": job_id,
                "status": "cancelled",
                "message": "Job has been marked for cancellation. Worker will stop processing.",
            }

        except Exception as e:
            logger.error("Failed to cancel job", job_id=job_id, error=str(e))
            raise

    async def get_sync_job_details(
        self, job_id: str, user_id: str | int
    ) -> dict[str, Any]:
        """Get a sync job's details from the database (source of truth).

        This is used by API endpoints that need to return JSON:API job resources
        (trigger/status/cancel) in a consistent shape.

        Raises:
            JobNotFoundException: If job doesn't exist or doesn't belong to user.
        """

        async with self.db_manager.get_session() as session:
            conn = await session.connection()
            repo = SyncJobRepository(conn)
            job = await repo.get_by_job_id(job_id)

            # Treat ownership mismatch as not-found to avoid leaking existence.
            if not job or str(job.user_id) != str(user_id):
                raise JobNotFoundException(job_id=job_id, message="Job not found")

            return {
                "job_id": job.job_id,
                "status": job.status,
                "sync_type": job.sync_type,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat()
                if job.completed_at
                else None,
                "error_message": job.error_message,
                "contacts_processed": job.contacts_processed,
                "contacts_created": job.contacts_created,
                "contacts_updated": job.contacts_updated,
                "contacts_deleted": job.contacts_deleted,
                "progress": job.progress,
            }

    async def get_queue_health(self) -> dict[str, Any]:
        """
        Get the health status of the task queue.

        Returns:
            Dictionary with queue health information
        """
        logger.debug("Checking queue health")

        try:
            # Check Redis connectivity
            pool = self.redis_pool
            if pool is None:
                pool = await self._get_arq_pool()
            await pool.ping()

            # Get queue statistics using ARQ's API
            queued_jobs = await pool.queued_jobs(queue_name=ARQ_QUEUE_NAME)
            queue_length = len(queued_jobs)

            # Update queue depth metric
            queue_depth.labels(worker_type=self.worker_type).set(queue_length)

            # Check if Redis is responsive
            start_time = datetime.now(UTC)
            pool = self.redis_pool
            if pool is None:
                pool = await self._get_arq_pool()
            await pool.ping()
            end_time = datetime.now(UTC)
            response_time_ms = (end_time - start_time).total_seconds() * 1000

            return {
                "status": "healthy",
                "redis_connected": True,
                "queue_length": queue_length,
                "response_time_ms": round(response_time_ms, 2),
                "checked_at": datetime.now(UTC).isoformat(),
            }

        except Exception as e:  # noqa: BLE001
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
        elif status == "failed":
            return "Job failed during processing"
        elif status == "not_found":
            return "Job not found or expired"
        else:
            return f"Job status: {status}"

    async def _store_user_job_association(
        self, user_id: str | int, job_id: str
    ) -> None:
        """
        Store user-job association for security checks.

        Args:
            user_id: User ID (string or integer)
            job_id: Job ID
        """
        try:
            # Store association with configurable expiration
            key = f"user_jobs:{user_id}"
            pool = self.redis_pool
            if pool is None:
                pool = await self._get_arq_pool()
            await pool.hset(key, job_id, "enqueued")
            expiry_seconds = self.settings.task_queue_user_job_expiry_hours * 3600
            await pool.expire(key, expiry_seconds)
            logger.debug("Stored user-job association", user_id=user_id, job_id=job_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to store user-job association",
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            # Don't raise - this is a security enhancement, not critical for functionality

    async def _verify_user_job_ownership(self, user_id: str | int, job_id: str) -> bool:
        """
        Verify that a user owns a specific job.

        Args:
            user_id: User ID (string or integer)
            job_id: Job ID

        Returns:
            True if user owns the job, False otherwise
        """
        try:
            key = f"user_jobs:{user_id}"
            pool = self.redis_pool
            if pool is None:
                pool = await self._get_arq_pool()
            result = await pool.hexists(key, job_id)
            owns_job = bool(result) if result is not None else False
            logger.debug(
                "Verified user-job ownership",
                user_id=user_id,
                job_id=job_id,
                owns_job=owns_job,
            )
            return owns_job
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to verify user-job ownership",
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            # On error, deny access for security
            return False

    async def list_sync_jobs(
        self,
        user_id: str | int,
        status: str | None = None,
        sync_type: str | None = None,
        integration_source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List sync jobs for a user with filtering and pagination.

        Args:
            user_id: User ID to filter by (string or integer)
            status: Filter by status (optional)
            sync_type: Filter by sync type (optional)
            integration_source: Filter by integration source (optional)
            date_from: Filter by created_at >= date_from (optional)
            date_to: Filter by created_at <= date_to (optional)
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            Tuple of (list of job dicts, total count)
        """
        async with self.db_manager.get_session() as session:
            async with session.begin():
                conn = await session.connection()
                repo = SyncJobRepository(conn)
                jobs, total = await repo.list_by_user(
                    user_id=str(user_id),
                    status=status,
                    sync_type=sync_type,
                    integration_source=integration_source,
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit,
                    offset=offset,
                )

                # Convert SyncJob objects to dicts
                job_dicts = [
                    {
                        "id": job.id,
                        "job_id": job.job_id,
                        "user_id": job.user_id,
                        "integration_source": job.integration_source,
                        "sync_type": job.sync_type,
                        "status": job.status,
                        "created_at": job.created_at.isoformat()
                        if job.created_at
                        else None,
                        "started_at": job.started_at.isoformat()
                        if job.started_at
                        else None,
                        "completed_at": job.completed_at.isoformat()
                        if job.completed_at
                        else None,
                        "error_message": job.error_message,
                        "contacts_processed": job.contacts_processed,
                        "contacts_created": job.contacts_created,
                        "contacts_updated": job.contacts_updated,
                        "contacts_deleted": job.contacts_deleted,
                        "progress": job.progress,
                    }
                    for job in jobs
                ]

                return job_dicts, total

    async def enqueue_calendar_webhook_setup(
        self,
        google_account_email: str,
        user_id: str | int,
        google_calendar_id: str,
    ) -> str:
        """Enqueue a Google Calendar webhook setup task.

        This is a lightweight task that registers a push notification channel
        for a specific Google Calendar. Unlike sync jobs, webhook setup tasks
        are not tracked in the sync_jobs table.

        Args:
            google_account_email: Google account email
            user_id: User ID
            google_calendar_id: The Google Calendar ID to register webhooks for

        Returns:
            ARQ job ID

        Raises:
            JobEnqueueError: If job enqueueing fails
        """
        logger.info(
            "Enqueueing calendar webhook setup",
            google_account_email=google_account_email,
            user_id=user_id,
            google_calendar_id=google_calendar_id,
        )

        try:
            pool = await self._get_arq_pool()

            job = await pool.enqueue_job(
                "setup_calendar_webhook",
                google_account_email,
                user_id,
                google_calendar_id,
                _defer_until=None,
                _queue_name=ARQ_QUEUE_NAME,
            )

            if not job:
                raise JobEnqueueError(
                    message="Failed to enqueue webhook setup - no job returned",
                    integration_source="google",
                    reason="ARQ pool returned None",
                )

            logger.info(
                "Successfully enqueued calendar webhook setup",
                job_id=job.job_id,
                google_calendar_id=google_calendar_id,
            )
            return job.job_id

        except Exception as e:
            logger.error(
                "Failed to enqueue calendar webhook setup",
                google_calendar_id=google_calendar_id,
                error=str(e),
            )
            raise

    async def enqueue_immich_sync(
        self, user_id: str | int, sync_type: str = "full"
    ) -> str:
        """
        Enqueue an Immich people sync job.

        Args:
            user_id: ID of the user requesting the sync (string or integer)
            sync_type: Type of sync ('full' or 'smart')

        Returns:
            Job ID for tracking the job status

        Raises:
            JobEnqueueError: If job enqueueing fails
            ConnectionError: If Redis connection fails
        """
        from core_shared.integration_constants import IMMICH_ARQ_QUEUE_NAME

        if sync_type == "incremental":
            sync_type = "smart"

        logger.info(
            "Enqueueing Immich sync job",
            user_id=user_id,
            sync_type=sync_type,
        )

        try:
            pool = await self._get_arq_pool()

            from opentelemetry.propagate import inject

            carrier: dict[str, str] = {}
            try:
                inject(carrier)
            except Exception:  # noqa: BLE001
                pass

            job = await pool.enqueue_job(
                "sync_immich_people",
                str(user_id),
                sync_type,
                otel_carrier=carrier,
                _defer_until=None,
                _queue_name=IMMICH_ARQ_QUEUE_NAME,
            )

            if not job:
                raise JobEnqueueError(
                    message="Failed to enqueue Immich sync job - no job returned",
                    integration_source="immich",
                    reason="ARQ pool returned None",
                )

            job_id = job.job_id
            logger.info(
                "Successfully enqueued Immich sync job",
                job_id=job_id,
                user_id=user_id,
                sync_type=sync_type,
            )

            # Store user-job association for security
            await self._store_user_job_association(user_id, job_id)

            # Persist job to database for history tracking
            async with self.db_manager.get_session() as session:
                async with session.begin():
                    conn = await session.connection()
                    repo = SyncJobRepository(conn)
                    await repo.create(
                        job_id=job_id,
                        user_id=str(user_id),
                        integration_source="immich",
                        sync_type=sync_type,
                        status="queued",
                    )

            return job_id

        except Exception as e:
            logger.error(
                "Failed to enqueue Immich sync job",
                user_id=user_id,
                sync_type=sync_type,
                error=str(e),
            )
            raise
