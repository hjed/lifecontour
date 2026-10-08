"""
Snipe-IT Integration Worker.

ARQ worker process that handles Snipe-IT integration tasks including
gear item sync, maintenance sync, and checkout operations.

This is the entry-point for the worker container. Actual task
implementations will be added in subsequent phases.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, NamedTuple, cast
from uuid import uuid4

from arq import Retry
from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared import (
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    default_retry_delay,
    generate_cron_jobs,
    generate_reconciliation_cron,
    reconcile_in_progress_parents,
    redis_settings_from_url,
)
from core_shared.fanout import (
    coerce_int,
    is_final_attempt,
    persist_fanout_children,
    record_child_terminal,
)
from core_shared.integration_constants import SNIPEIT_ARQ_QUEUE_NAME
from core_shared.logging import configure_logging, get_logger
from core_shared.models.sync_job import SyncJobStatus, SyncType
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.telemetry import setup_telemetry, trace_arq_job
from core_shared.worker_arq import DEFAULT_MAX_TRIES

from snipeit_models import SNIPEIT_DATETIME_FORMAT
from snipeit_rate_limiter import SnipeItRateLimitError
from snipeit_settings import SnipeItWorkerSettings
from snipeit_sync_window import (
    ListedRecord,
    ListingTracker,
    SyncResource,
    SyncWindow,
    resolve_sync_window,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

settings = SnipeItWorkerSettings()

configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)

logger = get_logger(__name__)


async def _get_auth_data(session_factory: Any, user_id: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT encrypted_api_key
                FROM user_snipe_it_auth
                WHERE user_id = :user_id AND needs_reauth = FALSE
                LIMIT 1
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "encrypted_api_key": row.encrypted_api_key,
        }


def _create_sync_service(
    user_id: str,
    auth_data: dict[str, Any],
    base_url: str,
    snipeit_user_id: str | None,
    worker_settings: SnipeItWorkerSettings,
    session_factory: Any,  # noqa: ARG001
    *,
    wait_on_limit: bool = True,
) -> Any:
    """Build a user's sync service over the shared limiter of their instance.

    By default its client waits for the limiter's budget, so a burst of events
    slows to Snipe-IT's pace instead of failing. Batch jobs pass
    ``wait_on_limit=False``: they defer themselves on ``SnipeItRateLimitError``.
    """
    from cryptography.fernet import Fernet

    from snipeit_api_client import SnipeItAPIClient
    from snipeit_sync_service import SnipeItSyncService

    fernet = Fernet(worker_settings.encryption_key.get_secret_value().encode())
    api_key = fernet.decrypt(auth_data["encrypted_api_key"]).decode()

    api_client = SnipeItAPIClient.create(
        base_url=base_url,
        api_key=api_key,
        wait_on_limit=wait_on_limit,
    )

    return SnipeItSyncService(
        api_client=api_client,
        user_id=user_id,
        snipeit_user_id=snipeit_user_id,
    )


class _SnipeItSettings(NamedTuple):
    base_url: str
    snipeit_user_id: str | None


class _NotConfiguredError(Exception):
    """A user's Snipe-IT settings or credentials are missing, so no sync can run."""


async def _get_settings(session_factory: Any, user_id: str) -> _SnipeItSettings | None:
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()

    if row is None or not row.base_url:
        return None
    return _SnipeItSettings(row.base_url, row.snipeit_user_id)


async def _open_sync_service(session_factory: Any, user_id: str) -> Any:
    """Build a batch job's sync service, or raise ``_NotConfiguredError``.

    Its client raises on a spent budget rather than wait: the batch jobs defer
    themselves on ``SnipeItRateLimitError`` (see ``_rate_limit_defer``).
    """
    snipeit = await _get_settings(session_factory, user_id)
    if snipeit is None:
        raise _NotConfiguredError("Snipe-IT settings not configured")

    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        raise _NotConfiguredError("Snipe-IT credentials not configured")

    return _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=snipeit.base_url,
        snipeit_user_id=snipeit.snipeit_user_id,
        worker_settings=settings,
        session_factory=session_factory,
        wait_on_limit=False,
    )


async def _set_job_status(
    session_factory: Any, job_id: str, status: SyncJobStatus, **kwargs: Any
) -> None:
    """Update a ``sync_jobs`` row in its own committed unit of work."""
    async with session_factory() as session:
        repo = SyncJobRepository(await session.connection())
        updated = await repo.update_status(job_id=job_id, status=status.value, **kwargs)
        await session.commit()
    if updated is None:
        logger.warning("Sync job row not found", job_id=job_id, status=status.value)


async def _record_child(
    session_factory: Any,
    child_job_id: str,
    parent_job_id: str | None,
    status: SyncJobStatus,
    error_message: str | None = None,
) -> None:
    """Mark a batch's row terminal and bump its parent's counter.

    A batch queued before the fan-out existed carries no parent, and no row.
    """
    if parent_job_id is None:
        return
    async with session_factory() as session:
        await record_child_terminal(
            SyncJobRepository(await session.connection()),
            child_job_id=child_job_id,
            parent_job_id=parent_job_id,
            status=status.value,
            error_message=error_message,
        )
        await session.commit()


async def _fail_parent(session_factory: Any, job_id: str, error_message: str) -> None:
    await _set_job_status(
        session_factory,
        job_id,
        SyncJobStatus.FAILED,
        completed_at=datetime.now(UTC),
        error_message=error_message,
    )


def _rate_limit_defer(ctx: dict[str, Any], retry_after: float | None) -> float:
    """How long to defer a rate-limited batch, in seconds.

    A deferred batch does not move its parent's ``updated_at``, so all of its
    retries together must fit the reconciler's staleness window, or the parent
    is failed as stuck before the batch runs again. Each deferral is capped at
    the window's share per attempt; a longer ``Retry-After`` just costs an
    attempt.
    """
    max_tries = coerce_int(ctx.get("max_tries"), DEFAULT_MAX_TRIES)
    cap = settings.reconciliation_stale_after_seconds / max_tries
    retry_count = coerce_int(ctx.get("job_try"), 1) - 1
    return min(retry_after or default_retry_delay(retry_count), cap)


def _format_cursor(cursor: datetime | None) -> str | None:
    """A cursor as ``sync_jobs`` stores it, Snipe-IT's ``Y-m-d H:i:s``."""
    return cursor.strftime(SNIPEIT_DATETIME_FORMAT) if cursor else None


# Batch size for the unchanged records a smart sync fetches anyway, matching
# the listing's page size that bounds every other batch.
_EXTRA_BATCH_SIZE = 50


async def _resolve_window(
    session_factory: Any, user_id: str, resource: SyncResource, sync_type: str
) -> SyncWindow:
    """Work out what this run fetches from the user's earlier completed runs."""
    from sqlalchemy import text

    async with session_factory() as session:
        repo = SyncJobRepository(await session.connection())
        last_completed = await repo.get_latest_completed_parent(
            user_id, "snipeit", resource
        )
        last_full = await repo.get_latest_completed_parent(
            user_id, "snipeit", resource, sync_type=SyncType.FULL.value
        )
        # Saving the settings (URL, user mapping) or the API key bumps these.
        settings_changed_at = (
            await session.execute(
                text("""
                    SELECT GREATEST(s.updated_at, a.updated_at)
                    FROM snipeit_settings s
                    LEFT JOIN user_snipe_it_auth a ON a.user_id = s.user_id
                    WHERE s.user_id = :user_id
                """),
                {"user_id": user_id},
            )
        ).scalar_one_or_none()
    return resolve_sync_window(
        SyncType(sync_type),
        last_completed=last_completed,
        last_full=last_full,
        now=datetime.now(UTC),
        settings_changed_at=settings_changed_at,
    )


async def _run_snipeit_fanout(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str,
    *,
    resource: SyncResource,
    list_batches: Callable[[Any], AsyncIterator[list[ListedRecord]]],
    batch_task: str,
    child_id_prefix: str,
    after_listing: Callable[[Any, list[int]], Awaitable[object]] | None = None,
    also_fetch: Callable[[Any, list[ListedRecord]], Awaitable[set[int]]] | None = None,
) -> dict[str, Any]:
    """Non-blocking fan-out shared by the asset and maintenance orchestrators.

    Marks the parent ``running`` and works out which records this run fetches:
    every one for a full sync, those changed since the last completed run for a
    smart one (see ``snipeit_sync_window``). It lists every page, runs
    ``after_listing`` on every listed id, then records the listing's cursor on
    the parent and persists a child row per page with records to fetch (the
    parent goes ``in_progress``, or ``completed`` when there is nothing to
    sync), committing before dispatching them. A smart run also fetches the
    ids ``also_fetch`` returns from every listed record, in batches of their own.
    Each batch finalises its own row; the reconciler finalises the parent. A
    listing that fails part-way dispatches nothing.

    Child ids are scoped to this run: arq keeps a finished job's result for
    ``keep_result`` seconds and refuses to enqueue an id it still holds, so ids
    shared across runs would silently drop a later run's batches.
    """
    job_id: str = ctx["job_id"]
    session_factory = ctx["session_factory"]

    await _set_job_status(
        session_factory,
        job_id,
        SyncJobStatus.RUNNING,
        started_at=datetime.now(UTC),
        progress=0,
    )

    try:
        sync_service = await _open_sync_service(session_factory, user_id)
    except _NotConfiguredError as exc:
        logger.error(str(exc), task=resource, user_id=user_id)
        await _fail_parent(session_factory, job_id, str(exc))
        return {"status": "error", "message": str(exc), "user_id": user_id}
    except Exception as exc:
        logger.exception("Snipe-IT fan-out failed", task=resource, user_id=user_id)
        await _fail_parent(session_factory, job_id, str(exc))
        raise

    try:
        window = await _resolve_window(session_factory, user_id, resource, sync_type)
        if window.escalation is not None:
            logger.warning(
                "Smart Snipe-IT sync is running as a full sync",
                task=resource,
                user_id=user_id,
                reason=window.escalation,
            )
        tracker = ListingTracker(window)
        batches = [
            ids
            async for page in list_batches(sync_service)
            if (ids := tracker.select(page))
        ]
        if after_listing is not None:
            await after_listing(sync_service, tracker.listed_ids)
        if also_fetch is not None and window.since is not None:
            selected = {record_id for ids in batches for record_id in ids}
            extra = sorted(await also_fetch(sync_service, tracker.listed) - selected)
            batches += [
                extra[start : start + _EXTRA_BATCH_SIZE]
                for start in range(0, len(extra), _EXTRA_BATCH_SIZE)
            ]

        # A retried attempt's earlier one may have queued batches, which arq
        # keeps with their original records under the same child ids, so this
        # listing is not what will be fetched: keep the cursor it started from.
        if coerce_int(ctx.get("job_try"), 1) > 1:
            cursor = _format_cursor(window.previous_cursor)
        else:
            cursor = tracker.cursor

        async with session_factory() as session:
            repo = SyncJobRepository(await session.connection())
            if not await repo.record_listing(
                job_id,
                resource=resource,
                cursor=cursor,
                sync_type=window.sync_type.value,
            ):
                logger.warning(
                    "Snipe-IT sync job row not found; its cursor is lost",
                    task=resource,
                    job_id=job_id,
                )
            child_ids = await persist_fanout_children(
                repo,
                parent_job_id=job_id,
                user_id=user_id,
                integration_source="snipeit",
                sync_type=window.sync_type.value,
                child_id_prefix=f"{child_id_prefix}:{user_id}:{job_id}:",
                count=len(batches),
            )
            await session.commit()
    except Exception as exc:
        logger.exception("Snipe-IT fan-out failed", task=resource, user_id=user_id)
        await _fail_parent(session_factory, job_id, str(exc))
        raise
    finally:
        await sync_service._api_client.close()

    # The child rows and parent state are committed; dispatch is now safe.
    enqueued = 0
    for position, (child_id, ids) in enumerate(zip(child_ids, batches, strict=True)):
        try:
            job = await ctx["redis"].enqueue_job(
                batch_task,
                user_id,
                ids,
                job_id,
                _job_id=child_id,
                _queue_name=settings.queue_name,
            )
        except Exception as exc:
            # A batch never queued never finalises its own row: fail it and the
            # rest here so the parent does not wait out the staleness window.
            logger.exception("Snipe-IT batch dispatch failed", task=resource)
            for unsent_id in child_ids[position:]:
                await _record_child(
                    session_factory,
                    unsent_id,
                    job_id,
                    SyncJobStatus.FAILED,
                    f"Batch was not enqueued: {exc}",
                )
            raise
        if job is None:
            # arq already holds this id: an earlier attempt of this run queued
            # it, so it still runs and finalises its own row.
            logger.warning(
                "Snipe-IT batch already enqueued; skipping",
                task=resource,
                child_job_id=child_id,
            )
        else:
            enqueued += 1

    logger.info(
        "Enqueued Snipe-IT sync batches",
        task=resource,
        user_id=user_id,
        batch_count=len(batches),
        enqueued=enqueued,
    )
    return {
        "status": "in_progress" if batches else "completed",
        "user_id": user_id,
        "batches_enqueued": enqueued,
    }


async def _run_snipeit_batch(
    ctx: dict[str, Any],
    user_id: str,
    ids: list[int],
    parent_job_id: str | None,
    *,
    noun: str,
    sync: Callable[[Any], Awaitable[dict[str, int]]],
) -> dict[str, int]:
    """Batch scaffolding shared by the asset and maintenance batch jobs.

    Records the batch's own row ``completed``, or ``failed`` when any item
    failed, the user is not configured, or the sync raised. A rate limit is
    retried by arq until the final attempt; arq retries nothing else.
    """
    session_factory = ctx["session_factory"]
    child_job_id: str = ctx["job_id"]

    try:
        sync_service = await _open_sync_service(session_factory, user_id)
    except _NotConfiguredError as exc:
        logger.error(str(exc), user_id=user_id)
        await _record_child(
            session_factory, child_job_id, parent_job_id, SyncJobStatus.FAILED, str(exc)
        )
        return {"synced": 0, "skipped": 0, "failed": len(ids)}
    except Exception as exc:
        await _record_child(
            session_factory, child_job_id, parent_job_id, SyncJobStatus.FAILED, str(exc)
        )
        raise

    try:
        result = await sync(sync_service)
    except SnipeItRateLimitError as exc:
        if not is_final_attempt(ctx):
            raise Retry(defer=_rate_limit_defer(ctx, exc.retry_after)) from exc
        await _record_child(
            session_factory, child_job_id, parent_job_id, SyncJobStatus.FAILED, str(exc)
        )
        raise
    except Exception as exc:
        await _record_child(
            session_factory, child_job_id, parent_job_id, SyncJobStatus.FAILED, str(exc)
        )
        raise
    finally:
        await sync_service._api_client.close()

    failed = result.get("failed", 0)
    if failed:
        await _record_child(
            session_factory,
            child_job_id,
            parent_job_id,
            SyncJobStatus.FAILED,
            f"{failed} of {len(ids)} {noun} failed to sync",
        )
    else:
        await _record_child(
            session_factory, child_job_id, parent_job_id, SyncJobStatus.COMPLETED
        )
    return dict(result)


@trace_arq_job
async def sync_snipeit_assets(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """Orchestrator job syncing Snipe-IT assets.

    A ``full`` sync fetches every asset; a ``smart`` one only those changed
    since the last completed sync, unless it has to run as a full one.
    """
    return await _run_snipeit_fanout(
        ctx,
        user_id,
        sync_type,
        resource="assets",
        list_batches=lambda service: service.list_asset_batches(),
        batch_task="sync_snipeit_asset_batch",
        child_id_prefix="snipeit_sync_batch",
    )


@trace_arq_job
async def sync_snipeit_asset_batch(
    ctx: dict[str, Any],
    user_id: str,
    asset_ids: list[int],
    parent_job_id: str | None = None,
) -> dict[str, int]:
    """Worker job to process a batch of Snipe-IT assets."""
    session_factory = ctx["session_factory"]
    return await _run_snipeit_batch(
        ctx,
        user_id,
        asset_ids,
        parent_job_id,
        noun="assets",
        sync=lambda service: service.sync_asset_batch(
            asset_ids=asset_ids, session_factory=session_factory
        ),
    )


@trace_arq_job
async def sync_snipeit_maintenances(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """Orchestrator job syncing Snipe-IT maintenance records.

    A ``full`` sync fetches every record; a ``smart`` one only those changed
    since the last completed sync and those not yet settled here (see
    ``unsettled_maintenance_ids``), unless it has to run as a full one. Both
    list every record, so deletions are reconciled on every run.
    """
    session_factory = ctx["session_factory"]

    async def _reconcile_deleted(service: Any, listed_ids: list[int]) -> None:
        # Only a listing that ran to the end says which records are gone: one
        # that raised part-way never gets here.
        await service.reconcile_deleted_maintenances(set(listed_ids), session_factory)

    return await _run_snipeit_fanout(
        ctx,
        user_id,
        sync_type,
        resource="maintenances",
        list_batches=lambda service: service.list_maintenance_batches(),
        batch_task="sync_snipeit_maintenance_batch",
        child_id_prefix="snipeit_maint_batch",
        after_listing=_reconcile_deleted,
        also_fetch=lambda service, listed: service.unsettled_maintenance_ids(
            listed, session_factory
        ),
    )


@trace_arq_job
async def sync_snipeit_maintenance_batch(
    ctx: dict[str, Any],
    user_id: str,
    maintenance_ids: list[int],
    parent_job_id: str | None = None,
) -> dict[str, int]:
    """Worker job to process a batch of Snipe-IT maintenance records."""
    session_factory = ctx["session_factory"]
    return await _run_snipeit_batch(
        ctx,
        user_id,
        maintenance_ids,
        parent_job_id,
        noun="maintenances",
        sync=lambda service: service.sync_maintenance_batch(
            maintenance_ids=maintenance_ids, session_factory=session_factory
        ),
    )


# The most (journal, asset) pairs one sweep run attempts per user. Each costs
# up to about 8 Snipe-IT calls, so at 120 calls a minute 40 pairs take under
# three minutes, inside arq's 300s job timeout. The pairs come oldest first, so
# the next run carries on where this one stopped.
SWEEP_MAX_PAIRS = 40


@trace_arq_job
async def periodic_checkin_all_snipeit_accounts(
    ctx: dict,  # type: ignore[type-arg]
) -> dict[str, int]:
    """Periodic safety net that finishes the gear usage pushes left unfinished.

    For every user with Snipe-IT configured, reconciles each (journal, asset)
    pair ``fetch_unsynced_gear_usage`` selects: a checkout that failed or was
    abandoned, and a check-in that is due. That is what repairs the pushes an
    event gave up on (e.g. when Snipe-IT kept rate limiting it), and it catches
    usage windows that only end with the passage of time.

    An asset's pairs come oldest first, and after one fails the asset's later
    pairs are left for the next run: with the earlier usage still out, their
    checkouts could only fail. A user still rate limited after the client's
    retries is left for the next run too.
    """
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    from snipeit_sync_service import fetch_unsynced_gear_usage

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT user_id, base_url, snipeit_user_id
                FROM snipeit_settings
                ORDER BY user_id
            """)
        )
        settings_rows = result.fetchall()

    reconciled = 0
    for row in settings_rows:
        user_id = row.user_id

        auth_data = await _get_auth_data(session_factory, user_id)
        if not auth_data:
            continue

        unsynced = await fetch_unsynced_gear_usage(session_factory, user_id)
        if not unsynced:
            continue

        sync_service = _create_sync_service(
            user_id=user_id,
            auth_data=auth_data,
            base_url=row.base_url,
            snipeit_user_id=row.snipeit_user_id,
            worker_settings=worker_settings,
            session_factory=session_factory,
        )
        try:
            reconciled += await _sweep_user(
                sync_service, unsynced, session_factory, user_id
            )
        finally:
            await sync_service._api_client.close()

    logger.info(
        "Completed periodic Snipe-IT gear usage sweep",
        accounts_found=len(settings_rows),
        reconciled=reconciled,
    )
    return {"accounts_found": len(settings_rows), "reconciled": reconciled}


async def _sweep_user(
    sync_service: Any, unsynced: list[Any], session_factory: Any, user_id: str
) -> int:
    """Reconcile one user's unsynced pairs in order; return how many succeeded.

    At most ``SWEEP_MAX_PAIRS`` are attempted. A pair skipped because its asset
    already failed this run is not an attempt, so an asset stuck with many
    unfinished pairs costs one attempt and leaves the run to the others.
    """
    failed_assets: set[int] = set()
    attempted = 0
    reconciled = 0
    for usage in unsynced:
        if attempted == SWEEP_MAX_PAIRS:
            break
        if usage.asset_id in failed_assets:
            continue
        attempted += 1
        try:
            await sync_service.reconcile_gear_usage(
                journal_id=usage.journal_id,
                session_factory=session_factory,
                asset_id=usage.asset_id,
            )
        except SnipeItRateLimitError:
            logger.warning(
                "Snipe-IT still rate limited; leaving the rest for the next sweep",
                user_id=user_id,
                journal_id=usage.journal_id,
            )
            break
        except Exception:  # noqa: BLE001
            failed_assets.add(usage.asset_id)
            logger.warning(
                "Periodic gear usage reconcile failed",
                user_id=user_id,
                journal_id=usage.journal_id,
                snipeit_asset_id=usage.asset_id,
                exc_info=True,
            )
        else:
            reconciled += 1
    return reconciled


# Each periodic run enqueues these orchestrators for every account. Snipe-IT
# sends no webhooks for asset changes or maintenance records, so this is the
# only way they arrive without a manual sync.
_PERIODIC_SYNC_JOBS = ("sync_snipeit_assets", "sync_snipeit_maintenances")


async def _schedule_periodic_sync(
    session: Any, redis: Any, function: str, user_id: str
) -> str | None:
    """Record one periodic sync's ``sync_jobs`` row, then enqueue it.

    The row is committed before the job is queued, so an orchestrator that runs
    at once always finds its parent row. A job that is not queued fails its row
    rather than leaving it queued for ever. Returns an error, or ``None``.
    """
    job_id = uuid4().hex
    try:
        await SyncJobRepository(await session.connection()).create(
            job_id=job_id,
            user_id=user_id,
            integration_source="snipeit",
            sync_type="smart",
            status=SyncJobStatus.QUEUED.value,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error(
            "Error recording periodic Snipe-IT sync job",
            function=function,
            user_id=user_id,
            exc_info=True,
        )
        return f"{function} failed for {user_id}: {exc!s}"

    try:
        job = await redis.enqueue_job(
            function,
            user_id,
            "smart",
            _job_id=job_id,
            _queue_name=SNIPEIT_ARQ_QUEUE_NAME,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Error enqueueing periodic Snipe-IT sync job",
            function=function,
            user_id=user_id,
            exc_info=True,
        )
        row_error, error = str(exc), f"{function} failed for {user_id}: {exc!s}"
    else:
        if job is not None:
            return None
        logger.warning(
            "Failed to enqueue periodic Snipe-IT sync job",
            function=function,
            user_id=user_id,
        )
        row_error, error = (
            "Job was not enqueued",
            f"{function} was not enqueued for {user_id}",
        )

    await SyncJobRepository(await session.connection()).update_status(
        job_id=job_id,
        status=SyncJobStatus.FAILED.value,
        completed_at=datetime.now(UTC),
        error_message=row_error,
    )
    await session.commit()
    return error


@trace_arq_job
async def periodic_sync_all_snipeit_accounts(
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Periodic sync that imports Snipe-IT assets and maintenance records.

    Called by ARQ cron. For every user with Snipe-IT settings and working auth,
    enqueues ``sync_snipeit_assets`` and ``sync_snipeit_maintenances`` with the
    'smart' sync type, writing each one's ``sync_jobs`` row first. Users whose auth
    needs re-authorising are left out, since their syncs could not run. A
    failure for one user is recorded in ``errors`` and the rest are still
    synced.

    Re-imports are idempotent: unchanged assets and maintenance records are
    skipped by version hash.
    """
    session_factory = ctx["session_factory"]

    from sqlalchemy import text

    jobs_enqueued = 0
    errors: list[str] = []

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT s.user_id
                FROM snipeit_settings s
                JOIN user_snipe_it_auth a ON a.user_id = s.user_id
                WHERE a.needs_reauth = FALSE
                ORDER BY s.user_id
            """)
        )
        accounts = result.fetchall()

        for row in accounts:
            user_id = str(row.user_id)
            for function in _PERIODIC_SYNC_JOBS:
                error = await _schedule_periodic_sync(
                    session, ctx["redis"], function, user_id
                )
                if error is None:
                    jobs_enqueued += 1
                else:
                    errors.append(error)

    logger.info(
        "Periodic Snipe-IT sync scheduling complete",
        accounts_found=len(accounts),
        jobs_enqueued=jobs_enqueued,
        errors_count=len(errors),
    )
    return {
        "status": "success",
        "accounts_found": len(accounts),
        "jobs_enqueued": jobs_enqueued,
        "errors": errors,
    }


async def _run_stream_consumer(session_factory: Any, worker_settings: Any) -> None:
    """Adapt the Snipe-IT stream consumer to the shared lifecycle factory's shape.

    ``build_worker_lifecycle`` calls ``consumer_factory(session_factory, settings)``;
    ``run_snipeit_stream_consumer`` takes ``redis_url``/``stream_name`` keywords, so
    this thin closure reads them off the worker settings.
    """
    from stream_consumer_tasks import run_snipeit_stream_consumer

    await run_snipeit_stream_consumer(
        session_factory=session_factory,
        redis_url=worker_settings.redis_url,
        stream_name=worker_settings.stream_name,
    )


# Shared lifecycle: build the database session factory, launch the stream
# consumer, and on shutdown cancel/reap it. Snipe-IT logs consumer errors in real
# time (done-callback) and does not close the session factory on shutdown — this
# matches the pre-migration startup/shutdown behaviour exactly.
_on_startup, _on_shutdown = build_worker_lifecycle(
    settings=settings,
    consumer_factory=_run_stream_consumer,
    close_session_factory=False,
    log_consumer_errors=True,
)


class WorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    """ARQ worker settings for the Snipe-IT integration worker.

    Operational defaults (``job_timeout``, ``keep_result``, retry backoff) come from
    :class:`core_shared.SharedARQWorkerSettings` and equal arq's own constructor
    defaults, so they apply unchanged. Two periodic jobs share the periodic-sync
    cadence: the asset and maintenance import
    (``periodic_sync_all_snipeit_accounts``) and the check-in sweep
    (``periodic_checkin_all_snipeit_accounts``), which finishes the gear usage
    checkouts and check-ins left unfinished, including returning assets whose
    usage period has ended. The fan-out reconciler (``reconcile_in_progress_parents``)
    always runs, finalising orchestrator parents from their batch rows. Only the
    functions list, consumer wiring, cron schedule, and documented overrides live
    here.
    """

    queue_name = SNIPEIT_ARQ_QUEUE_NAME

    # Task functions.
    functions: list[Any] = [
        sync_snipeit_assets,
        sync_snipeit_asset_batch,
        sync_snipeit_maintenances,
        sync_snipeit_maintenance_batch,
        periodic_checkin_all_snipeit_accounts,
        periodic_sync_all_snipeit_accounts,
        reconcile_in_progress_parents,
    ]

    # Cron schedule: the periodic asset/maintenance import and the check-in
    # sweep (shared helper; both empty when periodic sync is disabled). The
    # import runs half an hour after the sweep: they share one rate limit
    # budget (see ``rate_limiter_for``), so running together would only slow
    # both down, and a sweep that still ends rate limited resumes on the next
    # run. The fan-out reconciler
    # runs every few minutes regardless, since manual syncs fan out too.
    cron_jobs = [
        *generate_cron_jobs(
            periodic_sync_all_snipeit_accounts,
            enable_periodic_sync=settings.enable_periodic_sync,
            sync_interval_hours=settings.sync_interval_hours,
            minute=30,
        ),
        *generate_cron_jobs(
            periodic_checkin_all_snipeit_accounts,
            enable_periodic_sync=settings.enable_periodic_sync,
            sync_interval_hours=settings.sync_interval_hours,
        ),
        *generate_reconciliation_cron(reconcile_in_progress_parents),
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


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from arq import run_worker

    # Setup OpenTelemetry
    setup_telemetry(settings)

    logger.info("Starting Snipe-IT worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
