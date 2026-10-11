"""Enqueue an ARQ job together with its ``sync_jobs`` row.

Every tracked job's row is committed *before* the job is queued, under an id
generated here, so a worker that picks the job up at once always finds its row:
its status updates match, and the children it fans out satisfy the
``parent_job_id`` foreign key. A job that is not queued fails its row rather
than leaving it ``queued`` for ever, which nothing would ever reconcile.

Backend and worker enqueuers share this so a new integration cannot get the
order wrong.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core_shared.logging import get_logger
from core_shared.models.sync_job import SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository

logger = get_logger(__name__)

# The row error recorded when ARQ returns no job.
NOT_ENQUEUED_MESSAGE = "Job was not enqueued"


class JobEnqueuer(Protocol):
    """The part of ``arq.ArqRedis`` used here; core_shared does not depend on arq."""

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any:
        """Queue ``function``, returning the job or ``None`` if it was not queued."""
        ...


class JobNotEnqueuedError(Exception):
    """ARQ returned no job: one with this id is already queued or kept."""

    def __init__(self, function: str, job_id: str) -> None:
        super().__init__(f"{function} was not enqueued (job {job_id})")
        self.function = function
        self.job_id = job_id


async def enqueue_tracked_job(
    session: AsyncSession,
    redis: JobEnqueuer,
    function: str,
    *args: Any,
    queue_name: str,
    user_id: str,
    integration_source: str,
    sync_type: str,
    **job_kwargs: Any,
) -> str:
    """Commit a ``queued`` ``sync_jobs`` row, then queue its job; return the id.

    ``job_kwargs`` are passed on to ``enqueue_job`` (e.g. ``otel_carrier``).
    The session is committed rather than wrapped in ``begin()``, so callers may
    pass a session that has already run queries.

    Raises:
        JobNotEnqueuedError: ARQ returned no job; the row is marked failed.
        Exception: whatever the row insert or the enqueue raised. Nothing is
            queued after a failed insert; a failed enqueue marks the row failed.
    """
    job_id = uuid4().hex
    try:
        await SyncJobRepository(await session.connection()).create(
            job_id=job_id,
            user_id=user_id,
            integration_source=integration_source,
            sync_type=sync_type,
            status=SyncJobStatus.QUEUED.value,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    try:
        job = await redis.enqueue_job(
            function, *args, **job_kwargs, _job_id=job_id, _queue_name=queue_name
        )
    except (Exception, asyncio.CancelledError) as exc:
        await _fail_row(session, job_id, str(exc) or type(exc).__name__)
        raise
    if job is None:
        await _fail_row(session, job_id, NOT_ENQUEUED_MESSAGE)
        raise JobNotEnqueuedError(function, job_id)
    return job_id


async def _fail_row(session: AsyncSession, job_id: str, error_message: str) -> None:
    """Fail the row of a job that may not be queued; never raise over its error.

    An enqueue that raised (or was cancelled) may still have reached Redis, and
    a worker may already have started the job, so only a row still ``queued``
    is failed.
    """
    try:
        await SyncJobRepository(await session.connection()).fail_if_queued(
            job_id=job_id,
            completed_at=datetime.now(UTC),
            error_message=error_message,
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.error(
            "Failed to mark an unqueued sync job failed", job_id=job_id, exc_info=True
        )
        await session.rollback()
