"""
Immich Integration Worker.

ARQ worker process that handles Immich integration tasks including
contact/album sync with face-based matching.

This is the entry-point for the worker container. Phase 3 provides
periodic sync scheduling, manual sync triggers, and placeholder
sync tasks. Actual sync logic will be implemented in ITER11-002+.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any, cast

from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared import (
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    generate_cron_jobs,
    redis_settings_from_url,
)
from core_shared.integration_constants import IMMICH_ARQ_QUEUE_NAME
from core_shared.logging import (
    configure_logging,
    get_logger,
    set_job_id,
    set_worker_id,
)
from core_shared.telemetry import setup_telemetry, trace_arq_job

from immich_api_client import ImmichApiClient
from immich_auth_service import ImmichAuthService
from immich_settings import ImmichWorkerSettings
from immich_sync_service import ImmichSyncService

__version__ = "0.2.0"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

settings = ImmichWorkerSettings()

configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# ARQ sync tasks
# ---------------------------------------------------------------------------


async def _update_sync_job_status(
    session_factory: Any,
    job_id: str,
    status: str,
    **kwargs: Any,
) -> None:
    """Update a sync_jobs row via SyncJobRepository."""
    from core_shared.repositories.sync_job_repository import SyncJobRepository

    async with session_factory() as session:
        conn = await session.connection()
        repo = SyncJobRepository(conn)
        result = await repo.update_status(job_id=job_id, status=status, **kwargs)
        await session.commit()
        if result is None:
            logger.warning(
                "Failed to update sync job status - job not found",
                job_id=job_id,
                status=status,
            )


@trace_arq_job
async def sync_immich_people(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """ARQ task: orchestrate Immich People sync.

    Lists people pages from Immich and enqueues a `sync_immich_people_batch`
    job for each page. Each batch commits independently.

    Args:
        ctx: ARQ worker context (must contain `session_factory`).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dictionary with sync summary.
    """
    job_id = ctx.get("job_id", "unknown")
    session_factory = ctx["session_factory"]
    started_at = datetime.now(UTC)

    logger.info(
        "sync_immich_people started",
        user_id=user_id,
        sync_type=sync_type,
        job_id=job_id,
    )

    await _update_sync_job_status(
        session_factory, job_id, "running", started_at=started_at, progress=0
    )

    try:
        async with session_factory() as session:
            conn = await session.connection()

            auth_service = ImmichAuthService(settings.encryption_key.get_secret_value())
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                logger.warning("Immich credentials not found for user", user_id=user_id)
                await _update_sync_job_status(
                    session_factory,
                    job_id,
                    "failed",
                    completed_at=datetime.now(UTC),
                    error_message="Immich credentials not configured",
                )
                return {
                    "status": "error",
                    "message": "Immich credentials not configured",
                    "user_id": user_id,
                }

            batches_enqueued = 0
            api_client = ImmichApiClient.create(server_url, api_key)
            try:
                sync_service = ImmichSyncService(
                    api_client=api_client,
                    connection=conn,
                    user_id=user_id,
                )

                page_number = 0
                batch_jobs = []
                import asyncio

                from arq.jobs import Job

                async for people_batch in sync_service.list_people_batches():
                    page_number += 1
                    batch_job_id = f"immich-batch-{job_id}-p{page_number}"

                    job = await ctx["redis"].enqueue_job(
                        "sync_immich_people_batch",
                        user_id,
                        people_batch,
                        _job_id=batch_job_id,
                        _queue_name=IMMICH_ARQ_QUEUE_NAME,
                    )
                    if job:
                        batches_enqueued += 1
                        batch_jobs.append(job)
                        logger.info(
                            "Enqueued people batch job",
                            job_id=job.job_id,
                            batch_size=len(people_batch),
                            batch_number=page_number,
                        )
                    else:
                        batch_jobs.append(
                            Job(
                                batch_job_id,
                                ctx["redis"],
                                _queue_name=IMMICH_ARQ_QUEUE_NAME,
                            )
                        )
                        logger.info(
                            "People batch job already enqueued",
                            batch_job_id=batch_job_id,
                            batch_number=page_number,
                        )

            finally:
                await api_client.close()

        if batch_jobs:
            logger.info(
                "Waiting for batch jobs to complete",
                job_id=job_id,
                count=len(batch_jobs),
            )
            results = await asyncio.gather(
                *[j.result(timeout=290) for j in batch_jobs], return_exceptions=True
            )
            for res in results:
                if isinstance(res, Exception):
                    raise res

        await _update_sync_job_status(
            session_factory,
            job_id,
            "completed",
            completed_at=datetime.now(UTC),
            progress=100,
        )

        return {
            "status": "enqueued",
            "user_id": user_id,
            "sync_type": sync_type,
            "batches_enqueued": batches_enqueued,
        }

    except Exception as e:
        logger.exception(
            "sync_immich_people failed",
            user_id=user_id,
            error=str(e),
        )
        error_msg = "Immich people sync failed due to an internal error"
        await _update_sync_job_status(
            session_factory,
            job_id,
            "failed",
            completed_at=datetime.now(UTC),
            error_message=error_msg,
        )
        return {
            "status": "error",
            "message": error_msg,
            "user_id": user_id,
        }


@trace_arq_job
async def sync_immich_people_batch(
    ctx: dict[str, Any],
    user_id: str,
    people_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """ARQ task: process a batch of Immich people.

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        people_data: Serialized ImmichPerson dicts.
    """
    session_factory = ctx["session_factory"]

    logger.info(
        "sync_immich_people_batch started", user_id=user_id, batch_size=len(people_data)
    )

    try:
        async with session_factory() as session:
            conn = await session.connection()

            auth_service = ImmichAuthService(settings.encryption_key.get_secret_value())
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                raise ValueError("Immich credentials missing")

            api_client = ImmichApiClient.create(server_url, api_key)
            try:
                sync_service = ImmichSyncService(
                    api_client=api_client, connection=conn, user_id=user_id
                )
                result = await sync_service.sync_people_batch(people_data)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await api_client.close()

        return {
            "status": "success",
            "user_id": user_id,
            "created": result.created,
            "linked": result.linked,
            "unchanged": result.unchanged,
            "updated": result.updated,
            "skipped": result.skipped,
            "conflicts": result.conflicts,
        }
    except Exception as e:
        logger.exception(
            "sync_immich_people_batch failed", user_id=user_id, error=str(e)
        )
        raise


@trace_arq_job
async def sync_immich_albums(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """ARQ task: orchestrate Immich album sync.

    Lists album-ID batches from Immich and enqueues a ``sync_immich_album_batch``
    job for each batch (mirroring ``sync_immich_people``), so the heavy per-album
    work is fanned out and no single batch times out. It then waits for the
    batches and marks the sync job ``completed`` only if they all succeed, or
    ``failed`` if any batch fails — so the job status reflects the real outcome
    rather than just dispatch.

    Args:
        ctx: ARQ worker context (must contain ``session_factory``).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dictionary with album sync summary.
    """
    job_id = ctx.get("job_id", "unknown")
    session_factory = ctx["session_factory"]
    started_at = datetime.now(UTC)

    logger.info(
        "sync_immich_albums started",
        user_id=user_id,
        sync_type=sync_type,
        job_id=job_id,
    )

    await _update_sync_job_status(
        session_factory, job_id, "running", started_at=started_at, progress=0
    )

    try:
        import asyncio

        from arq.jobs import Job

        batch_jobs: list[Any] = []
        batches_enqueued = 0

        async with session_factory() as session:
            conn = await session.connection()

            auth_service = ImmichAuthService(settings.encryption_key.get_secret_value())
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                logger.warning("Immich credentials not found for user", user_id=user_id)
                await _update_sync_job_status(
                    session_factory,
                    job_id,
                    "failed",
                    completed_at=datetime.now(UTC),
                    error_message="Immich credentials not configured",
                )
                return {
                    "status": "error",
                    "message": "Immich credentials not configured",
                    "user_id": user_id,
                }

            api_client = ImmichApiClient.create(server_url, api_key)
            try:
                sync_service = ImmichSyncService(
                    api_client=api_client, connection=conn, user_id=user_id
                )

                batch_number = 0
                async for album_batch in sync_service.list_album_id_batches():
                    batch_number += 1
                    batch_job_id = f"immich-album-batch-{job_id}-b{batch_number}"

                    job = await ctx["redis"].enqueue_job(
                        "sync_immich_album_batch",
                        user_id,
                        album_batch,
                        _job_id=batch_job_id,
                        _queue_name=IMMICH_ARQ_QUEUE_NAME,
                    )
                    if job:
                        batches_enqueued += 1
                        batch_jobs.append(job)
                        logger.info(
                            "Enqueued album batch job",
                            job_id=job.job_id,
                            batch_size=len(album_batch),
                            batch_number=batch_number,
                        )
                    else:
                        batch_jobs.append(
                            Job(
                                batch_job_id,
                                ctx["redis"],
                                _queue_name=IMMICH_ARQ_QUEUE_NAME,
                            )
                        )
                        logger.info(
                            "Album batch job already enqueued",
                            batch_job_id=batch_job_id,
                            batch_number=batch_number,
                        )
            finally:
                await api_client.close()

        # Wait for the fanned-out batches so the sync job status reflects whether
        # the albums actually synced; a failed batch propagates and marks the
        # job failed below.
        if batch_jobs:
            results = await asyncio.gather(
                *[j.result(timeout=290) for j in batch_jobs], return_exceptions=True
            )
            for res in results:
                if isinstance(res, Exception):
                    raise res

        await _update_sync_job_status(
            session_factory,
            job_id,
            "completed",
            completed_at=datetime.now(UTC),
            progress=100,
        )

        return {
            "status": "completed",
            "user_id": user_id,
            "sync_type": sync_type,
            "batches_enqueued": batches_enqueued,
        }

    except Exception as e:
        logger.exception("sync_immich_albums failed", user_id=user_id, error=str(e))
        error_msg = "Immich album sync failed due to an internal error"
        await _update_sync_job_status(
            session_factory,
            job_id,
            "failed",
            completed_at=datetime.now(UTC),
            error_message=error_msg,
        )
        return {
            "status": "error",
            "message": error_msg,
            "user_id": user_id,
        }


@trace_arq_job
async def sync_immich_album_batch(
    ctx: dict[str, Any],
    user_id: str,
    album_ids: list[str],
) -> dict[str, Any]:
    """ARQ task: process a batch of Immich albums.

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        album_ids: Immich album UUIDs to process.
    """
    session_factory = ctx["session_factory"]

    logger.info(
        "sync_immich_album_batch started",
        user_id=user_id,
        batch_size=len(album_ids),
    )

    try:
        async with session_factory() as session:
            conn = await session.connection()

            auth_service = ImmichAuthService(settings.encryption_key.get_secret_value())
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                raise ValueError("Immich credentials missing")

            api_client = ImmichApiClient.create(server_url, api_key)
            try:
                sync_service = ImmichSyncService(
                    api_client=api_client,
                    connection=conn,
                    user_id=user_id,
                    server_url=server_url,
                )
                result = await sync_service.sync_albums_batch(album_ids)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await api_client.close()

        return {
            "status": "success",
            "user_id": user_id,
            "created": result.created,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "errors": result.errors,
        }
    except Exception as e:
        logger.exception(
            "sync_immich_album_batch failed", user_id=user_id, error=str(e)
        )
        raise


async def _unlink_immich_reference_for_event(
    session: Any,
    external_id: str,
    contact_id: int | None,
) -> dict[str, Any]:
    """Unlink an orphaned Immich link locally, triggered by a domain event.

    Immich exposes no person-delete, so reconciling a same-service merge clash
    means removing the source contact's canonical ``sync_metadata`` link (keyed
    by the source's remote person id) — never a remote call. Idempotent:
    deleting zero rows (the link was already cleaned inline by the merge) is
    success.

    Args:
        session: Database session
        external_id: Immich person id of the orphaned source link
        contact_id: Internal id of the source contact whose link is unlinked

    Returns:
        Result dict with status
    """
    from sqlalchemy import text

    await session.execute(
        text("""
            DELETE FROM sync_metadata
            WHERE integration_source = :integration_source
              AND external_id = :external_id
        """),
        {"integration_source": "immich", "external_id": external_id},
    )

    logger.info(
        "Unlinked orphaned Immich reference via event",
        contact_id=contact_id,
        external_id=external_id,
    )
    return {"status": "unlinked", "external_id": external_id}


async def _process_contact_merged_event(
    ctx: dict[str, Any], event_data: dict[str, Any]
) -> dict[str, Any]:
    """Reconcile a contact merge with Immich.

    The merge already re-pointed the survivor's external links and deleted the
    source contact's *local* ``external_references`` / ``sync_metadata`` inline.
    A same-service clash — both contacts linked to Immich — is surfaced on
    ``event_data["external_collisions"]``; each entry carries the source
    contact's orphaned remote id (``source_external_id``).

    Because the Immich API exposes no person-delete, this keeps the survivor's
    link and unlinks the source's orphaned local reference (and any residual
    sync metadata) without any remote call. The survivor's Immich person is
    reconciled separately by the ``ContactUpdated`` event the merge also emits,
    so it is intentionally not re-pushed here.

    Args:
        ctx: ARQ-compatible context dictionary with session_factory
        event_data: The ``ContactMerged`` payload (survivor/source ids +
            ``external_collisions``)

    Returns:
        Task result dictionary with reconciliation status
    """
    source_contact_id = event_data.get("source_contact_id")
    collisions = event_data.get("external_collisions") or []

    # Validate each collision rather than indexing it: a malformed entry must
    # be skipped (and logged), never raise, so the event is still acknowledged
    # and never dead-letters. Only person references can be unlinked here.
    source_external_ids: list[str] = []
    for collision in collisions:
        if collision.get("external_system") != "immich":
            continue
        if collision.get("external_entity_type") != "person":
            logger.warning(
                "Skipping Immich collision with unexpected entity type",
                source_contact_id=source_contact_id,
                external_entity_type=collision.get("external_entity_type"),
            )
            continue
        source_external_id = collision.get("source_external_id")
        if not source_external_id:
            logger.warning(
                "Skipping malformed Immich collision missing source_external_id",
                source_contact_id=source_contact_id,
            )
            continue
        source_external_ids.append(source_external_id)

    if not source_external_ids:
        logger.info(
            "ContactMerged has no Immich collisions, skipping",
            source_contact_id=source_contact_id,
        )
        return {"status": "skipped", "reason": "no_immich_collisions"}

    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        results = []
        for source_external_id in source_external_ids:
            result = await _unlink_immich_reference_for_event(
                session=session,
                external_id=source_external_id,
                contact_id=source_contact_id,
            )
            results.append(result)
        await session.commit()

    return {"status": "success", "results": results}


@trace_arq_job
async def process_contact_event(
    ctx: dict[str, Any], event_type: str, event_data: dict[str, Any]
) -> dict[str, Any]:
    """Process a single contact event for Immich outbound sync.

    Receives domain events (ContactCreated, ContactUpdated, ContactBirthdayChanged,
    ContactMerged) and pushes the changes to Immich for all synced accounts.

    Args:
        ctx: ARQ-compatible context dictionary with session_factory
        event_type: The domain event type
        event_data: The event payload containing contact_id

    Returns:
        Task result dictionary with sync status
    """
    job_id = ctx.get("job_id", "unknown")
    set_job_id(job_id)
    set_worker_id(settings.worker_id)

    # ContactMerged carries no contact_id (only survivor/source ids and the
    # external collisions to reconcile), so it is handled before the
    # contact_id guard below.
    if event_type == "ContactMerged":
        return await _process_contact_merged_event(ctx, event_data)

    contact_id = event_data.get("contact_id")
    if not contact_id:
        logger.error(
            "Contact event missing contact_id",
            event_type=event_type,
            job_id=job_id,
        )
        return {"status": "error", "error": "Missing contact_id"}

    logger.info(
        "Processing contact event",
        job_id=job_id,
        event_type=event_type,
        contact_id=contact_id,
    )

    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        # Find all Immich integrations for all users
        auth_service = ImmichAuthService(settings.encryption_key.get_secret_value())
        conn = await session.connection()

        event_user_id = event_data.get("user_id")
        if event_user_id is not None:
            user_ids = [str(event_user_id)]
        else:
            user_ids = await auth_service.get_all_user_ids(conn)

        if not user_ids:
            logger.info(
                "No Immich integrations found, skipping contact event",
                contact_id=contact_id,
                event_type=event_type,
            )
            return {"status": "skipped", "reason": "no_immich_integrations"}

        results: list[dict[str, Any]] = []
        # NOTE: This system is single-user by design. We iterate all
        # user_immich_auth rows for forward-compatibility, but in
        # practice there is only one user. The same pattern is used
        # in periodic_sync_all_immich_accounts.
        for user_id in user_ids:
            try:
                conn = await session.connection()
                auth_service = ImmichAuthService(
                    settings.encryption_key.get_secret_value()
                )
                api_key = await auth_service.get_api_key(user_id, conn)
                server_url = await auth_service.get_server_url(user_id, conn)

                if not api_key or not server_url:
                    results.append({"user_id": user_id, "status": "skipped"})
                    continue

                api_client = ImmichApiClient.create(server_url, api_key)
                try:
                    sync_service = ImmichSyncService(
                        api_client=api_client, connection=conn, user_id=user_id
                    )
                    result = await sync_service.sync_contact_outbound(contact_id)
                    await session.commit()
                    results.append({"user_id": user_id, "result": result})
                except Exception as inner_e:  # noqa: BLE001
                    await session.rollback()
                    logger.error(
                        "Error syncing contact to Immich",
                        user_id=user_id,
                        contact_id=contact_id,
                        error=str(inner_e),
                    )
                    results.append(
                        {"user_id": user_id, "status": "error", "error": str(inner_e)}
                    )
                finally:
                    await api_client.close()

            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Error processing contact event for user",
                    user_id=user_id,
                    contact_id=contact_id,
                    error=str(e),
                )
                results.append({"user_id": user_id, "status": "error", "error": str(e)})

        return {"status": "success", "results": results}


async def periodic_sync_all_immich_accounts(
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Periodic sync wrapper that syncs all active Immich accounts.

    This function is called by ARQ cron jobs and enqueues individual
    ``sync_immich_people`` tasks for each connected Immich
    integration using 'smart' sync type.

    Args:
        ctx: ARQ context dictionary containing Redis pool and session_factory.

    Returns:
        Dictionary with sync summary (accounts_found, jobs_enqueued, errors).
    """
    logger.info("Starting periodic sync for all Immich accounts")

    session_factory = ctx["session_factory"]

    accounts_found = 0
    jobs_enqueued = 0
    errors: list[str] = []

    try:
        async with session_factory() as session:
            from sqlalchemy import text

            stmt = text("""
                SELECT user_id
                FROM user_immich_auth
                ORDER BY user_id
            """)
            result = await session.execute(stmt)
            accounts = result.fetchall()

            accounts_found = len(accounts)
            logger.info(
                "Found active Immich accounts for periodic sync",
                accounts_count=accounts_found,
            )

            for row in accounts:
                user_id = row.user_id

                try:
                    job = await ctx["redis"].enqueue_job(
                        "sync_immich_people",
                        str(user_id),
                        "smart",
                        _queue_name=IMMICH_ARQ_QUEUE_NAME,
                    )

                    if job:
                        jobs_enqueued += 1
                        logger.info(
                            "Enqueued periodic Immich sync job",
                            job_id=job.job_id,
                            user_id=user_id,
                        )

                        from core_shared.repositories.sync_job_repository import (
                            SyncJobRepository,
                        )

                        conn = await session.connection()
                        repo = SyncJobRepository(conn)
                        await repo.create(
                            job_id=job.job_id,
                            user_id=str(user_id),
                            integration_source="immich",
                            sync_type="smart",
                            status="queued",
                        )
                        await session.commit()
                    else:
                        error_msg = f"Failed to enqueue Immich sync for user {user_id}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic Immich sync job",
                            user_id=user_id,
                        )

                except Exception as e:  # noqa: BLE001
                    await session.rollback()
                    error_msg = (
                        f"Error enqueueing Immich sync for user {user_id}: {e!s}"
                    )
                    errors.append(error_msg)
                    logger.error(
                        "Error enqueueing periodic Immich sync job",
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

        logger.info(
            "Periodic Immich sync scheduling complete",
            accounts_found=accounts_found,
            jobs_enqueued=jobs_enqueued,
            errors_count=len(errors),
        )

        return {
            "status": "success",
            "accounts_found": accounts_found,
            "jobs_enqueued": jobs_enqueued,
            "errors": errors,
        }

    except Exception:
        logger.error(
            "Fatal error during periodic Immich sync",
            accounts_found=accounts_found,
            jobs_enqueued=jobs_enqueued,
            exc_info=True,
        )
        raise


# ---------------------------------------------------------------------------
# ARQ worker configuration
# ---------------------------------------------------------------------------


async def _run_stream_consumer(session_factory: Any, worker_settings: Any) -> None:
    """Adapt the Immich stream consumer to the shared lifecycle factory's shape.

    ``build_worker_lifecycle`` calls ``consumer_factory(session_factory, settings)``;
    ``run_immich_stream_consumer`` takes ``redis_url``/``stream_name`` keywords, so
    this thin closure reads them off the worker settings.
    """
    from stream_consumer_tasks import run_immich_stream_consumer

    await run_immich_stream_consumer(
        session_factory=session_factory,
        redis_url=worker_settings.redis_url,
        stream_name=worker_settings.stream_name,
    )


# Shared lifecycle: build the database session factory, launch the stream
# consumer, and on shutdown cancel/reap it. Immich logs consumer errors in real
# time (done-callback) and does not close the session factory on shutdown — this
# matches the pre-migration startup/shutdown behaviour exactly.
_on_startup, _on_shutdown = build_worker_lifecycle(
    settings=settings,
    consumer_factory=_run_stream_consumer,
    close_session_factory=False,
    log_consumer_errors=True,
)


class WorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    """ARQ worker settings for the Immich integration worker.

    Operational defaults (``job_timeout``, ``keep_result``, retry backoff) come from
    :class:`core_shared.SharedARQWorkerSettings` and equal arq's own constructor
    defaults, so they apply unchanged. Only the functions list, consumer wiring,
    cron schedule, and documented overrides live here.
    """

    queue_name = IMMICH_ARQ_QUEUE_NAME

    # Task functions.
    functions: list[Any] = [
        sync_immich_people,
        sync_immich_people_batch,
        sync_immich_albums,
        sync_immich_album_batch,
        periodic_sync_all_immich_accounts,
        process_contact_event,
    ]

    # Worker lifecycle (shared factory). Cast to arq's StartupShutdown Protocol:
    # the hooks accept ``ctx`` but the shared LifecycleHook alias is a plain
    # positional Callable, which the Protocol's named-parameter form rejects.
    on_startup: StartupShutdown = cast("StartupShutdown", _on_startup)
    on_shutdown: StartupShutdown = cast("StartupShutdown", _on_shutdown)

    # Redis settings (shared helper).
    redis_settings = redis_settings_from_url(settings.redis_url)

    # Documented override:
    # - health_check_interval=30: arq's ``get_kwargs`` reads only this leaf class's
    #   attributes, so the inherited shared 30 is invisible and arq would fall back
    #   to its default of 3600. Redeclaring 30 preserves the pre-migration 30s ping.
    health_check_interval = 30

    # Periodic sync cron (shared helper; empty when periodic sync is disabled).
    cron_jobs = generate_cron_jobs(
        periodic_sync_all_immich_accounts,
        enable_periodic_sync=settings.enable_periodic_sync,
        sync_interval_hours=settings.sync_interval_hours,
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from arq import run_worker

    # Setup OpenTelemetry
    setup_telemetry(settings)

    logger.info("Starting Immich worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
