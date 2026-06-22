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
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared import (
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    generate_cron_jobs,
    generate_reconciliation_cron,
    reconcile_in_progress_parents,
    redis_settings_from_url,
)
from core_shared.fanout import (
    is_final_attempt as _is_final_attempt,
)
from core_shared.fanout import (
    persist_fanout_children as _persist_fanout_children,
)
from core_shared.fanout import (
    record_child_terminal as _record_child_terminal,
)
from core_shared.integration_constants import IMMICH_ARQ_QUEUE_NAME
from core_shared.logging import (
    configure_logging,
    get_logger,
    set_job_id,
    set_worker_id,
)
from core_shared.repositories.sync_job_repository import SyncJobRepository
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


async def _record_child_failure(
    session_factory: Any,
    child_job_id: str,
    parent_job_id: str,
    error_message: str,
) -> None:
    """Mark a child row ``failed`` and bump the parent's ``failed_children``.

    Runs in its own committed unit of work because the originating batch
    transaction has already been rolled back when this is called.
    """
    async with session_factory() as session:
        conn = await session.connection()
        repo = SyncJobRepository(conn)
        await _record_child_terminal(
            repo,
            child_job_id=child_job_id,
            parent_job_id=parent_job_id,
            status="failed",
            error_message=error_message,
        )
        await session.commit()


async def _run_immich_fanout(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str,
    *,
    label: str,
    list_batches: Callable[[ImmichSyncService], AsyncIterator[Any]],
    batch_task: str,
    child_id_template: str,
    failure_message: str,
) -> dict[str, Any]:
    """Shared non-blocking fan-out orchestration for albums and people.

    Drains ``list_batches`` into memory, persists a linked child row per batch,
    marks the parent ``in_progress`` (or ``completed`` when empty), commits, then
    dispatches one ``batch_task`` per batch — passing the parent ``job_id`` so
    each child can update its own row and the parent counters. Returns
    immediately; the reconciler finalises the parent. The two public
    orchestrators differ only in the values passed here.
    """
    job_id = ctx.get("job_id", "unknown")
    session_factory = ctx["session_factory"]
    started_at = datetime.now(UTC)

    logger.info(
        "immich fanout started",
        task=label,
        user_id=user_id,
        sync_type=sync_type,
        job_id=job_id,
    )

    await _update_sync_job_status(
        session_factory, job_id, "running", started_at=started_at, progress=0
    )

    try:
        batches: list[Any] = []
        async with session_factory() as session:
            conn = await session.connection()
            repo = SyncJobRepository(conn)

            auth_service = ImmichAuthService(settings.encryption_key.get_secret_value())
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                logger.warning("Immich credentials not found for user", user_id=user_id)
                await repo.update_status(
                    job_id=job_id,
                    status="failed",
                    completed_at=datetime.now(UTC),
                    error_message="Immich credentials not configured",
                )
                await session.commit()
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
                async for batch in list_batches(sync_service):
                    batches.append(batch)
            finally:
                await api_client.close()

            child_ids = await _persist_fanout_children(
                repo,
                parent_job_id=job_id,
                user_id=user_id,
                integration_source="immich",
                sync_type=sync_type,
                child_id_prefix=child_id_template.format(job_id=job_id),
                count=len(batches),
            )
            await session.commit()

        # Children rows + parent state are committed; dispatch is now safe.
        dispatched = 0
        for child_id, batch in zip(child_ids, batches, strict=True):
            job = await ctx["redis"].enqueue_job(
                batch_task,
                user_id,
                batch,
                job_id,
                _job_id=child_id,
                _queue_name=IMMICH_ARQ_QUEUE_NAME,
            )
            if job is None:
                # Deterministic _job_id means a prior run already enqueued this
                # child; the child row still exists, so the reconciler stays
                # correct. Surface it rather than silently over-reporting.
                logger.warning(
                    "immich child batch already enqueued; skipping",
                    task=label,
                    job_id=job_id,
                    child_job_id=child_id,
                )
            else:
                dispatched += 1

        logger.info(
            "immich fanout dispatched",
            task=label,
            job_id=job_id,
            expected_children=len(batches),
            dispatched=dispatched,
        )

        return {
            "status": "in_progress" if batches else "completed",
            "user_id": user_id,
            "sync_type": sync_type,
            "batches_enqueued": len(batches),
        }

    except Exception as e:
        logger.exception(
            "immich fanout failed", task=label, user_id=user_id, error=str(e)
        )
        await _update_sync_job_status(
            session_factory,
            job_id,
            "failed",
            completed_at=datetime.now(UTC),
            error_message=failure_message,
        )
        return {
            "status": "error",
            "message": failure_message,
            "user_id": user_id,
        }


async def _run_immich_batch(
    ctx: dict[str, Any],
    user_id: str,
    parent_job_id: str | None,
    *,
    label: str,
    batch_size: int,
    process: Callable[[Any, Any, str], Awaitable[Any]],
    build_result: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    """Shared child-batch scaffolding for albums and people.

    Resolves credentials, runs ``process(api_client, conn, server_url)`` inside a
    committed unit of work, and — when ``parent_job_id`` is set — marks this
    child's row ``completed`` and increments the parent's ``completed_children``
    (only if the row update matched). On a final-attempt failure it records the
    child ``failed`` and increments ``failed_children``; a non-final failure
    re-raises untouched so ARQ retries without double-counting.
    """
    session_factory = ctx["session_factory"]
    child_job_id = ctx.get("job_id", "unknown")

    logger.info(
        "immich batch started", task=label, user_id=user_id, batch_size=batch_size
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
                result = await process(api_client, conn, server_url)
                if parent_job_id:
                    await _record_child_terminal(
                        SyncJobRepository(conn),
                        child_job_id=child_job_id,
                        parent_job_id=parent_job_id,
                        status="completed",
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await api_client.close()

        return build_result(result)
    except Exception as e:
        logger.exception(
            "immich batch failed", task=label, user_id=user_id, error=str(e)
        )
        if parent_job_id and _is_final_attempt(ctx):
            await _record_child_failure(
                session_factory, child_job_id, parent_job_id, str(e)
            )
        raise


@trace_arq_job
async def sync_immich_people(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """ARQ task: orchestrate Immich People sync (non-blocking fan-out).

    Lists people pages from Immich, persists one linked child ``sync_jobs`` row
    per page, enqueues a ``sync_immich_people_batch`` job for each, marks the
    parent ``in_progress`` and returns immediately — it no longer blocks on the
    children. The shared reconciliation cron finalises the parent against the
    child rows.

    Args:
        ctx: ARQ worker context (must contain `session_factory` and `redis`).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dictionary with sync summary.
    """
    return await _run_immich_fanout(
        ctx,
        user_id,
        sync_type,
        label="sync_immich_people",
        list_batches=lambda svc: svc.list_people_batches(),
        batch_task="sync_immich_people_batch",
        child_id_template="immich-batch-{job_id}-p",
        failure_message="Immich people sync failed due to an internal error",
    )


@trace_arq_job
async def sync_immich_people_batch(
    ctx: dict[str, Any],
    user_id: str,
    people_data: list[dict[str, Any]],
    parent_job_id: str | None = None,
) -> dict[str, Any]:
    """ARQ task: process a batch of Immich people.

    On success the batch marks its own child ``sync_jobs`` row ``completed`` and
    atomically increments the parent's ``completed_children``; on a final-attempt
    failure it marks the row ``failed`` and increments ``failed_children``. A
    non-final failure just re-raises so ARQ retries without touching the
    counters. ``parent_job_id`` is optional so legacy/direct invocations still
    work (counters are simply skipped).

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        people_data: Serialized ImmichPerson dicts.
        parent_job_id: Orchestrator job id for child-row + counter bookkeeping.
    """

    async def _process(api_client: Any, conn: Any, _server_url: str) -> Any:
        sync_service = ImmichSyncService(
            api_client=api_client, connection=conn, user_id=user_id
        )
        return await sync_service.sync_people_batch(people_data)

    def _build_result(result: Any) -> dict[str, Any]:
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

    return await _run_immich_batch(
        ctx,
        user_id,
        parent_job_id,
        label="sync_immich_people_batch",
        batch_size=len(people_data),
        process=_process,
        build_result=_build_result,
    )


@trace_arq_job
async def sync_immich_albums(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """ARQ task: orchestrate Immich album sync (non-blocking fan-out).

    Lists album-ID batches from Immich, persists one linked child ``sync_jobs``
    row per batch, enqueues a ``sync_immich_album_batch`` job for each, marks the
    parent ``in_progress`` and returns immediately — it no longer blocks on
    ``asyncio.gather``. The shared reconciliation cron finalises the parent
    (``completed``/``failed``) against the child rows.

    Args:
        ctx: ARQ worker context (must contain ``session_factory`` and ``redis``).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dictionary with album sync summary.
    """
    return await _run_immich_fanout(
        ctx,
        user_id,
        sync_type,
        label="sync_immich_albums",
        list_batches=lambda svc: svc.list_album_id_batches(),
        batch_task="sync_immich_album_batch",
        child_id_template="immich-album-batch-{job_id}-b",
        failure_message="Immich album sync failed due to an internal error",
    )


@trace_arq_job
async def sync_immich_album_batch(
    ctx: dict[str, Any],
    user_id: str,
    album_ids: list[str],
    parent_job_id: str | None = None,
) -> dict[str, Any]:
    """ARQ task: process a batch of Immich albums.

    On success the batch marks its own child ``sync_jobs`` row ``completed`` and
    atomically increments the parent's ``completed_children``; on a final-attempt
    failure it marks the row ``failed`` and increments ``failed_children``. A
    non-final failure just re-raises so ARQ retries without touching the
    counters. ``parent_job_id`` is optional so legacy/direct invocations still
    work (counters are simply skipped).

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        album_ids: Immich album UUIDs to process.
        parent_job_id: Orchestrator job id for child-row + counter bookkeeping.
    """

    async def _process(api_client: Any, conn: Any, server_url: str) -> Any:
        sync_service = ImmichSyncService(
            api_client=api_client,
            connection=conn,
            user_id=user_id,
            server_url=server_url,
        )
        return await sync_service.sync_albums_batch(album_ids)

    def _build_result(result: Any) -> dict[str, Any]:
        return {
            "status": "success",
            "user_id": user_id,
            "created": result.created,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "errors": result.errors,
        }

    return await _run_immich_batch(
        ctx,
        user_id,
        parent_job_id,
        label="sync_immich_album_batch",
        batch_size=len(album_ids),
        process=_process,
        build_result=_build_result,
    )


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
        reconcile_in_progress_parents,
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

    # Cron schedule: the periodic-sync cron (shared helper; empty when periodic
    # sync is disabled) plus the always-on fan-out reconciliation cron, which
    # finalises non-blocking ``IN_PROGRESS`` parents against their child rows.
    cron_jobs = [
        *generate_cron_jobs(
            periodic_sync_all_immich_accounts,
            enable_periodic_sync=settings.enable_periodic_sync,
            sync_interval_hours=settings.sync_interval_hours,
        ),
        *generate_reconciliation_cron(reconcile_in_progress_parents),
    ]


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from arq import run_worker

    # Setup OpenTelemetry
    setup_telemetry(settings)

    logger.info("Starting Immich worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
