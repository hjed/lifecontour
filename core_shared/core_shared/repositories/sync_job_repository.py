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
    ) -> SyncJob:
        """
        Create a new sync job record.

        Args:
            job_id: ARQ job ID
            user_id: User who initiated the sync
            integration_source: Integration source (e.g., 'google_contacts')
            sync_type: Type of sync ('smart' or 'full')
            status: Initial status (default: 'queued')

        Returns:
            Created SyncJob
        """
        now = datetime.now(UTC)

        query = text("""
            INSERT INTO sync_jobs
                (job_id, user_id, integration_source, sync_type, status,
                 created_at, updated_at)
            VALUES
                (:job_id, :user_id, :integration_source, :sync_type, :status,
                 :created_at, :updated_at)
            RETURNING id, job_id, user_id, integration_source, sync_type, status,
                      created_at, started_at, completed_at, error_message,
                      contacts_processed, contacts_created, contacts_updated,
                      contacts_deleted, progress, updated_at
        """)

        result = await self.conn.execute(
            query,
            {
                "job_id": job_id,
                "user_id": user_id,
                "integration_source": integration_source,
                "sync_type": sync_type,
                "status": status,
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
            "RETURNING id, job_id, user_id, integration_source, sync_type, status, "
            "created_at, started_at, completed_at, error_message, "
            "contacts_processed, contacts_created, contacts_updated, "
            "contacts_deleted, progress, updated_at"
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
        query = text("""
            SELECT id, job_id, user_id, integration_source, sync_type, status,
                   created_at, started_at, completed_at, error_message,
                   contacts_processed, contacts_created, contacts_updated,
                   contacts_deleted, progress, updated_at
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
        query_sql = """
            SELECT id, job_id, user_id, integration_source, sync_type, status,
                   created_at, started_at, completed_at, error_message,
                   contacts_processed, contacts_created, contacts_updated,
                   contacts_deleted, progress, updated_at
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
        )
