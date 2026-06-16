"""
SQL repository for SyncJob with filtering and pagination support.

This repository provides methods for creating, updating, and querying sync jobs
with support for filtering by status, sync type, date range, and pagination.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from core_shared.models.sync_job import SyncJob

# Full sync_jobs column list (static identifiers) reused across SELECT/RETURNING
# clauses so every query stays in sync as the schema grows.
_SYNC_JOB_COLUMNS = (
    "id, job_id, user_id, integration_source, sync_type, status, "
    "created_at, started_at, completed_at, error_message, "
    "contacts_processed, contacts_created, contacts_updated, "
    "contacts_deleted, progress, updated_at, "
    "parent_job_id, expected_children, completed_children, failed_children"
)


class SyncJobRepository:
    """Repository for managing sync job records."""

    def __init__(self, conn: AsyncConnection):
        """
        Initialize the repository.

        Args:
            conn: Database connection
        """
        self.conn = conn

    async def create(
        self,
        job_id: str,
        user_id: str,
        integration_source: str,
        sync_type: str,
        status: str = "queued",
        parent_job_id: str | None = None,
    ) -> SyncJob:
        """
        Create a new sync job record.

        Args:
            job_id: ARQ job ID
            user_id: User who initiated the sync
            integration_source: Integration source (e.g., 'google')
            sync_type: Type of sync ('smart' or 'full')
            status: Initial status (default: 'queued')
            parent_job_id: Orchestrator job_id this job is a child of, or None for
                top-level jobs (links a child batch job to its parent)

        Returns:
            Created SyncJob
        """
        now = datetime.now(UTC)

        query = text(f"""
            INSERT INTO sync_jobs
                (job_id, user_id, integration_source, sync_type, status,
                 parent_job_id, created_at, updated_at)
            VALUES
                (:job_id, :user_id, :integration_source, :sync_type, :status,
                 :parent_job_id, :created_at, :updated_at)
            RETURNING {_SYNC_JOB_COLUMNS}
        """)

        result = await self.conn.execute(
            query,
            {
                "job_id": job_id,
                "user_id": user_id,
                "integration_source": integration_source,
                "sync_type": sync_type,
                "status": status,
                "parent_job_id": parent_job_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to create sync job")

        return self._row_to_sync_job(row)

    async def update_status(
        self,
        job_id: str,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        contacts_processed: int | None = None,
        contacts_created: int | None = None,
        contacts_updated: int | None = None,
        contacts_deleted: int | None = None,
        progress: int | None = None,
    ) -> SyncJob | None:
        """
        Update sync job status and progress.

        Args:
            job_id: ARQ job ID
            status: New status
            started_at: When the job started (optional)
            completed_at: When the job completed (optional)
            error_message: Error message if failed (optional)
            contacts_processed: Number of contacts processed (optional)
            contacts_created: Number of contacts created (optional)
            contacts_updated: Number of contacts updated (optional)
            contacts_deleted: Number of contacts deleted (optional)
            progress: Progress percentage 0-100 (optional)

        Returns:
            Updated SyncJob or None if not found
        """
        now = datetime.now(UTC)

        # Build update query dynamically based on provided fields
        # Note: All field names are hardcoded constants, not user input
        update_fields = ["status = :status", "updated_at = :updated_at"]
        params = {"job_id": job_id, "status": status, "updated_at": now}

        if started_at is not None:
            update_fields.append("started_at = :started_at")
            params["started_at"] = started_at

        if completed_at is not None:
            update_fields.append("completed_at = :completed_at")
            params["completed_at"] = completed_at

        if error_message is not None:
            update_fields.append("error_message = :error_message")
            params["error_message"] = error_message

        if contacts_processed is not None:
            update_fields.append("contacts_processed = :contacts_processed")
            params["contacts_processed"] = contacts_processed

        if contacts_created is not None:
            update_fields.append("contacts_created = :contacts_created")
            params["contacts_created"] = contacts_created

        if contacts_updated is not None:
            update_fields.append("contacts_updated = :contacts_updated")
            params["contacts_updated"] = contacts_updated

        if contacts_deleted is not None:
            update_fields.append("contacts_deleted = :contacts_deleted")
            params["contacts_deleted"] = contacts_deleted

        if progress is not None:
            update_fields.append("progress = :progress")
            params["progress"] = progress

        # Build SQL with static field names (safe from SQL injection)
        set_clause = ", ".join(update_fields)
        sql = (
            "UPDATE sync_jobs "
            "SET " + set_clause + " "
            "WHERE job_id = :job_id "
            "RETURNING " + _SYNC_JOB_COLUMNS
        )
        query = text(sql)

        result = await self.conn.execute(query, params)
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_sync_job(row)

    async def get_by_job_id(self, job_id: str) -> SyncJob | None:
        """
        Get a sync job by its job ID.

        Args:
            job_id: ARQ job ID

        Returns:
            SyncJob or None if not found
        """
        query = text(f"""
            SELECT {_SYNC_JOB_COLUMNS}
            FROM sync_jobs
            WHERE job_id = :job_id
        """)

        result = await self.conn.execute(query, {"job_id": job_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_sync_job(row)

    async def list_by_user(
        self,
        user_id: str,
        status: str | None = None,
        sync_type: str | None = None,
        integration_source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SyncJob], int]:
        """
        List sync jobs for a user with filtering and pagination.

        Args:
            user_id: User ID to filter by
            status: Filter by status (optional)
            sync_type: Filter by sync type (optional)
            integration_source: Filter by integration source (optional)
            date_from: Filter by created_at >= date_from (optional)
            date_to: Filter by created_at <= date_to (optional)
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            Tuple of (list of SyncJobs, total count)
        """
        # Build WHERE clause dynamically with static field names
        where_clauses = ["user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}

        if status is not None:
            where_clauses.append("status = :status")
            params["status"] = status

        if sync_type is not None:
            where_clauses.append("sync_type = :sync_type")
            params["sync_type"] = sync_type

        if integration_source is not None:
            where_clauses.append("integration_source = :integration_source")
            params["integration_source"] = integration_source

        if date_from is not None:
            where_clauses.append("created_at >= :date_from")
            params["date_from"] = date_from

        if date_to is not None:
            where_clauses.append("created_at <= :date_to")
            params["date_to"] = date_to

        # Build WHERE clause string from static condition fragments
        where_clause = " AND ".join(where_clauses)

        # Get total count
        count_sql = """
            SELECT COUNT(*) as total
            FROM sync_jobs
        """
        if where_clause:
            count_sql += f" WHERE {where_clause}"
        count_query = text(count_sql)

        count_result = await self.conn.execute(count_query, params)
        total = count_result.scalar() or 0

        # Get paginated results
        query_sql = f"""
            SELECT {_SYNC_JOB_COLUMNS}
            FROM sync_jobs
        """
        if where_clause:
            query_sql += f" WHERE {where_clause}"
        query_sql += """
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        query = text(query_sql)

        result = await self.conn.execute(query, params)
        rows = result.fetchall()

        jobs = [self._row_to_sync_job(row) for row in rows]

        return jobs, total

    async def get_recent_failures(
        self,
        integration_source: str | None = None,
        hours: int = 24,
        limit: int = 10,
    ) -> list[SyncJob]:
        """
        Get recent failed sync jobs.

        Args:
            integration_source: Filter by integration source (optional)
            hours: Number of hours to look back (default: 24)
            limit: Maximum number of results (default: 10)

        Returns:
            List of recent failed SyncJobs
        """
        # Build WHERE clause
        where_clauses = [
            "status = 'failed'",
            "created_at >= NOW() - (:hours * INTERVAL '1 hour')",
        ]
        params: dict[str, Any] = {"hours": hours, "limit": limit}

        if integration_source is not None:
            where_clauses.append("integration_source = :integration_source")
            params["integration_source"] = integration_source

        where_clause = " AND ".join(where_clauses)

        query_sql = f"""
            SELECT {_SYNC_JOB_COLUMNS}
            FROM sync_jobs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """
        query = text(query_sql)

        result = await self.conn.execute(query, params)
        rows = result.fetchall()

        return [self._row_to_sync_job(row) for row in rows]

    async def get_job_statistics(
        self,
        integration_source: str | None = None,
        hours: int = 24,
    ) -> dict[str, Any]:
        """
        Get job statistics for monitoring.

        Args:
            integration_source: Filter by integration source (optional)
            hours: Number of hours to look back (default: 24)

        Returns:
            Dictionary with job statistics including:
            - total_jobs: Total number of jobs
            - completed_jobs: Number of completed jobs
            - failed_jobs: Number of failed jobs
            - cancelled_jobs: Number of cancelled jobs
            - running_jobs: Number of running jobs
            - queued_jobs: Number of queued jobs
            - retry_count: Number of jobs that were retried (failed then succeeded)
        """
        # Build WHERE clause
        where_clause = "created_at >= NOW() - (:hours * INTERVAL '1 hour')"
        params: dict[str, Any] = {"hours": hours}

        if integration_source is not None:
            where_clause += " AND integration_source = :integration_source"
            params["integration_source"] = integration_source

        query_sql = f"""
            SELECT
                COUNT(*) as total_jobs,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_jobs,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_jobs,
                COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled_jobs,
                COUNT(CASE WHEN status = 'running' THEN 1 END) as running_jobs,
                COUNT(CASE WHEN status = 'queued' THEN 1 END) as queued_jobs
            FROM sync_jobs
            WHERE {where_clause}
        """
        query = text(query_sql)

        result = await self.conn.execute(query, params)
        row = result.fetchone()

        if not row:
            return {
                "total_jobs": 0,
                "completed_jobs": 0,
                "failed_jobs": 0,
                "cancelled_jobs": 0,
                "running_jobs": 0,
                "queued_jobs": 0,
                "retry_count": 0,
            }

        return {
            "total_jobs": row.total_jobs or 0,
            "completed_jobs": row.completed_jobs or 0,
            "failed_jobs": row.failed_jobs or 0,
            "cancelled_jobs": row.cancelled_jobs or 0,
            "running_jobs": row.running_jobs or 0,
            "queued_jobs": row.queued_jobs or 0,
            # Note: Retry tracking requires additional schema changes to track
            # job retry attempts. Currently not implemented as ARQ handles retries
            # internally and we track final job status only.
            "retry_count": 0,
        }

    async def set_expected_children(
        self, job_id: str, expected_children: int
    ) -> SyncJob | None:
        """
        Set the expected child count on a parent (orchestrator) job.

        Args:
            job_id: Parent orchestrator job ID
            expected_children: Number of child jobs dispatched

        Returns:
            Updated SyncJob or None if the parent was not found
        """
        now = datetime.now(UTC)
        query = text(
            "UPDATE sync_jobs "
            "SET expected_children = :expected_children, updated_at = :updated_at "
            "WHERE job_id = :job_id "
            "RETURNING " + _SYNC_JOB_COLUMNS
        )

        result = await self.conn.execute(
            query,
            {
                "job_id": job_id,
                "expected_children": expected_children,
                "updated_at": now,
            },
        )
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_sync_job(row)

    async def increment_completed_children(self, parent_job_id: str) -> None:
        """Atomically increment a parent's completed-children counter."""
        await self._increment_child_counter(parent_job_id, "completed_children")

    async def increment_failed_children(self, parent_job_id: str) -> None:
        """Atomically increment a parent's failed-children counter."""
        await self._increment_child_counter(parent_job_id, "failed_children")

    async def _increment_child_counter(self, parent_job_id: str, column: str) -> None:
        """
        Atomically increment a child counter on the parent row.

        The increment is performed entirely in SQL (``col = col + 1``) so it is
        safe under concurrent batch-job completions. ``column`` is restricted to a
        known set of identifiers, so it cannot be used for SQL injection.

        Args:
            parent_job_id: Parent orchestrator job ID
            column: Counter column to increment
        """
        allowed = {"completed_children", "failed_children"}
        if column not in allowed:
            raise ValueError(f"Invalid counter column: {column}")

        query = text(
            f"UPDATE sync_jobs "
            f"SET {column} = {column} + 1, updated_at = :updated_at "
            f"WHERE job_id = :parent_job_id"
        )
        await self.conn.execute(
            query,
            {"parent_job_id": parent_job_id, "updated_at": datetime.now(UTC)},
        )

    async def list_children(self, parent_job_id: str) -> list[SyncJob]:
        """
        List all child jobs linked to a parent orchestrator job.

        Args:
            parent_job_id: Parent orchestrator job ID

        Returns:
            List of child SyncJobs (oldest first)
        """
        query = text(f"""
            SELECT {_SYNC_JOB_COLUMNS}
            FROM sync_jobs
            WHERE parent_job_id = :parent_job_id
            ORDER BY created_at ASC
        """)

        result = await self.conn.execute(query, {"parent_job_id": parent_job_id})
        rows = result.fetchall()

        return [self._row_to_sync_job(row) for row in rows]

    async def aggregate_children(self, parent_job_id: str) -> dict[str, int]:
        """
        Aggregate child-job statuses for a parent (authoritative completion check).

        Child rows are the source of truth for parent completion; the counter
        columns are only a fast path.

        Args:
            parent_job_id: Parent orchestrator job ID

        Returns:
            Dict with ``total``, ``completed`` and ``failed`` child counts
        """
        query = text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed
            FROM sync_jobs
            WHERE parent_job_id = :parent_job_id
        """)

        result = await self.conn.execute(query, {"parent_job_id": parent_job_id})
        row = result.fetchone()

        if not row:
            return {"total": 0, "completed": 0, "failed": 0}

        return {
            "total": row.total or 0,
            "completed": row.completed or 0,
            "failed": row.failed or 0,
        }

    def _row_to_sync_job(self, row: Any) -> SyncJob:
        """Convert a database row to a SyncJob object."""
        return SyncJob(
            id=row.id,
            job_id=row.job_id,
            user_id=row.user_id,
            integration_source=row.integration_source,
            sync_type=row.sync_type,
            status=row.status,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error_message=row.error_message,
            contacts_processed=row.contacts_processed,
            contacts_created=row.contacts_created,
            contacts_updated=row.contacts_updated,
            contacts_deleted=row.contacts_deleted,
            progress=row.progress,
            updated_at=row.updated_at,
            parent_job_id=row.parent_job_id,
            expected_children=row.expected_children,
            completed_children=row.completed_children,
            failed_children=row.failed_children,
        )
