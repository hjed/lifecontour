"""
Snipe-IT Integration Worker.

ARQ worker process that handles Snipe-IT integration tasks including
gear item sync, maintenance sync, and checkout operations.

This is the entry-point for the worker container. Actual task
implementations will be added in subsequent phases.
"""

from __future__ import annotations

import sys
from typing import Any, cast

from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared import (
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    generate_cron_jobs,
    redis_settings_from_url,
)
from core_shared.integration_constants import SNIPEIT_ARQ_QUEUE_NAME
from core_shared.logging import configure_logging, get_logger
from core_shared.telemetry import setup_telemetry, trace_arq_job

from snipeit_settings import SnipeItWorkerSettings

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
) -> Any:
    from cryptography.fernet import Fernet

    from snipeit_api_client import SnipeItAPIClient
    from snipeit_sync_service import SnipeItSyncService

    fernet = Fernet(worker_settings.encryption_key.get_secret_value().encode())
    api_key = fernet.decrypt(auth_data["encrypted_api_key"]).decode()

    api_client = SnipeItAPIClient.create(
        base_url=base_url,
        api_key=api_key,
    )

    return SnipeItSyncService(
        api_client=api_client,
        user_id=user_id,
        snipeit_user_id=snipeit_user_id,
    )


@trace_arq_job
async def sync_snipeit_assets(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    sync_type: str = "full",
) -> None:
    """Orchestrator job for full sync of Snipe-IT assets."""
    # TODO: Implement smart sync behavior using sync_type parameter
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        redis = ctx["redis"]

        batch_count = 0
        async for asset_ids in sync_service.list_asset_batches():
            if not asset_ids:
                continue

            job_id = f"snipeit_sync_batch:{user_id}:{batch_count}"
            await redis.enqueue_job(
                "sync_snipeit_asset_batch",
                user_id,
                asset_ids,
                _job_id=job_id,
                _queue_name=worker_settings.queue_name,
            )
            batch_count += 1

        logger.info(
            "Enqueued Snipe-IT sync batches",
            user_id=user_id,
            batch_count=batch_count,
        )

    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_snipeit_asset_batch(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    asset_ids: list[int],
) -> dict[str, int]:
    """Worker job to process a batch of Snipe-IT assets."""
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(asset_ids)}

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(asset_ids)}

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        result = await sync_service.sync_asset_batch(
            asset_ids=asset_ids,
            session_factory=session_factory,
        )
        return dict(result)
    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_snipeit_maintenances(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    sync_type: str = "full",
) -> None:
    """Orchestrator job for full sync of Snipe-IT maintenance records."""
    # TODO: Implement smart sync behavior using sync_type parameter
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        redis = ctx["redis"]

        # Fetch all maintenance IDs and enqueue batch jobs
        batch_count = 0
        async for maintenance_ids in sync_service.list_maintenance_batches():
            if not maintenance_ids:
                continue

            job_id = f"snipeit_maint_batch:{user_id}:{batch_count}"
            await redis.enqueue_job(
                "sync_snipeit_maintenance_batch",
                user_id,
                maintenance_ids,
                _job_id=job_id,
                _queue_name=worker_settings.queue_name,
            )
            batch_count += 1

        logger.info(
            "Enqueued Snipe-IT maintenance sync batches",
            user_id=user_id,
            batch_count=batch_count,
        )

    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_snipeit_maintenance_batch(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    maintenance_ids: list[int],
) -> dict[str, int]:
    """Worker job to process a batch of Snipe-IT maintenance records."""
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(maintenance_ids)}

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(maintenance_ids)}

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        result = await sync_service.sync_maintenance_batch(
            maintenance_ids=maintenance_ids,
            session_factory=session_factory,
        )
        return dict(result)
    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def periodic_checkin_all_snipeit_accounts(
    ctx: dict,  # type: ignore[type-arg]
) -> dict[str, int]:
    """Periodic safety-net that checks in assets whose usage period has ended.

    For every user with Snipe-IT configured, finds successful checkouts that
    have no successful check-in yet and whose resolved check-in date has passed,
    then returns those assets in Snipe-IT, backdated to the local check-in date
    when it is before today. Complements the event-driven triggers
    (journal deletion / update / immediate-on-create) by catching usage windows
    that only become past with the passage of time.
    """
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    from snipeit_api_client import SnipeItAPIError
    from snipeit_sync_service import fetch_overdue_gear_usage

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT user_id, base_url, snipeit_user_id
                FROM snipeit_settings
                ORDER BY user_id
            """)
        )
        settings_rows = result.fetchall()

    accounts_found = len(settings_rows)
    checked_in = 0

    for row in settings_rows:
        user_id = row.user_id
        base_url = row.base_url
        snipeit_user_id = row.snipeit_user_id

        auth_data = await _get_auth_data(session_factory, user_id)
        if not auth_data:
            continue

        overdue_usages = await fetch_overdue_gear_usage(session_factory, user_id)
        if not overdue_usages:
            continue

        sync_service = _create_sync_service(
            user_id=user_id,
            auth_data=auth_data,
            base_url=base_url,
            snipeit_user_id=snipeit_user_id,
            worker_settings=worker_settings,
            session_factory=session_factory,
        )

        try:
            for overdue in overdue_usages:
                try:
                    did_checkin = await sync_service.push_checkin_create(
                        journal_id=overdue.journal_id,
                        session_factory=session_factory,
                        note=overdue.note,
                        checkin_at=overdue.snipeit_checkin_at(),
                    )
                    if did_checkin:
                        checked_in += 1
                        # The checkout may be recorded on a date the journal has
                        # since changed; with the asset back, re-record it.
                        await sync_service.reconcile_gear_usage(
                            journal_id=overdue.journal_id,
                            session_factory=session_factory,
                        )
                except SnipeItAPIError as exc:
                    if exc.status_code in (403, 404):
                        logger.debug(
                            "Skipped periodic checkin (not found/forbidden)",
                            journal_id=overdue.journal_id,
                            user_id=user_id,
                            status_code=exc.status_code,
                        )
                    else:
                        logger.warning(
                            "Periodic checkin failed",
                            journal_id=overdue.journal_id,
                            user_id=user_id,
                            exc_info=True,
                        )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Periodic checkin failed",
                        journal_id=overdue.journal_id,
                        user_id=user_id,
                        exc_info=True,
                    )
        finally:
            await sync_service._api_client.close()

    logger.info(
        "Completed periodic Snipe-IT check-in sweep",
        accounts_found=accounts_found,
        checked_in=checked_in,
    )
    return {"accounts_found": accounts_found, "checked_in": checked_in}


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
    defaults, so they apply unchanged. The only periodic job is the check-in sweep
    (``periodic_checkin_all_snipeit_accounts``), which returns assets whose usage
    period has ended. Only the functions list, consumer wiring, cron schedule, and
    documented overrides live here.
    """

    queue_name = SNIPEIT_ARQ_QUEUE_NAME

    # Task functions.
    functions: list[Any] = [
        sync_snipeit_assets,
        sync_snipeit_asset_batch,
        sync_snipeit_maintenances,
        sync_snipeit_maintenance_batch,
        periodic_checkin_all_snipeit_accounts,
    ]

    # Cron schedule: the periodic check-in sweep (shared helper; empty when
    # periodic sync is disabled).
    cron_jobs = generate_cron_jobs(
        periodic_checkin_all_snipeit_accounts,
        enable_periodic_sync=settings.enable_periodic_sync,
        sync_interval_hours=settings.sync_interval_hours,
    )

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
