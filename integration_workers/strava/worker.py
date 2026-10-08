#!/usr/bin/env python3
"""
Strava Integration Worker.

This worker processes Strava webhook events and activity sync tasks
using ARQ. It runs as a separate process from the main FastAPI
application and also launches a Redis Streams consumer for domain
event fan-out.
"""

import random
from datetime import UTC, datetime
from typing import Any, cast

from arq import Retry, func, run_worker
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
from core_shared.integration_constants import STRAVA_ARQ_QUEUE_NAME
from core_shared.logging import configure_logging, get_logger
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.telemetry import setup_telemetry, trace_arq_job

from strava_rate_limiter import StravaRateLimitError
from strava_settings import StravaSettings

# Global settings instance
settings = StravaSettings()

# Configure structured logging using shared module
configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)

logger = get_logger(__name__)

# Strava's rate limits require many retries to reach the daily-limit reset
# (~20 hours of hourly deferrals). ARQ does not put ``max_tries`` in the job
# context, so the batch passes this to ``is_final_attempt`` itself.
STRAVA_MAX_TRIES = 20

# Default deferral when Strava provides no retry_after hint (daily limit).
# 1 hour ensures STRAVA_MAX_TRIES covers ~20 hours, enough to reach midnight UTC.
_DEFAULT_RATE_LIMIT_DEFER = 60 * 60  # 1 hour


def _rate_limit_defer(exc: StravaRateLimitError) -> int:
    """Calculate a deferral duration for a rate-limited ARQ retry.

    Uses the server-provided ``retry_after`` when available (e.g. remaining
    time in the 15-minute window) plus random jitter to avoid thundering
    herd.  When ``retry_after`` is ``None`` (daily limit), falls back to
    a conservative 15-minute default.
    """
    base = (
        int(exc.retry_after)
        if exc.retry_after is not None
        else _DEFAULT_RATE_LIMIT_DEFER
    )
    jitter = random.randint(10, 120)
    return base + jitter


async def _resolve_user_for_athlete(
    session_factory: Any, athlete_id: int
) -> tuple[str, dict[str, Any]] | None:
    """Look up user_id and auth data for a Strava athlete_id.

    Args:
        session_factory: SQLAlchemy async session factory.
        athlete_id: Strava numeric athlete ID.

    Returns:
        Tuple of (user_id, auth_dict) or None if not found.
    """
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT user_id, encrypted_access_token, encrypted_refresh_token
                FROM user_strava_auth
                WHERE athlete_id = :athlete_id
                LIMIT 1
            """),
            {"athlete_id": athlete_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return str(row.user_id), {
            "encrypted_access_token": row.encrypted_access_token,
            "encrypted_refresh_token": row.encrypted_refresh_token,
        }


async def _resolve_user_by_id(
    session_factory: Any, user_id: str
) -> dict[str, Any] | None:
    """Look up auth data for a given user_id.

    Args:
        session_factory: SQLAlchemy async session factory.
        user_id: Internal user ID string.

    Returns:
        Auth dict with encrypted tokens, or None if not found.
    """
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT encrypted_access_token, encrypted_refresh_token
                FROM user_strava_auth
                WHERE user_id = :user_id
                LIMIT 1
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "encrypted_access_token": row.encrypted_access_token,
            "encrypted_refresh_token": row.encrypted_refresh_token,
        }


async def _update_user_tokens(
    session_factory: Any,
    user_id: str,
    tokens: Any,
    auth_service: Any,
) -> None:
    from sqlalchemy import text

    encrypted_access = auth_service.encrypt(tokens.access_token)
    encrypted_refresh = auth_service.encrypt(tokens.refresh_token)

    async with session_factory() as session:
        await session.execute(
            text("""
                UPDATE user_strava_auth
                SET encrypted_access_token = :access,
                    encrypted_refresh_token = :refresh,
                    expires_at = :expires_at,
                    updated_at = NOW()
                WHERE user_id = :user_id
            """),
            {
                "access": encrypted_access,
                "refresh": encrypted_refresh,
                "expires_at": tokens.expires_at,
                "user_id": user_id,
            },
        )
        await session.commit()


def _create_sync_service(
    user_id: str,
    auth_data: dict[str, Any],
    worker_settings: StravaSettings,
    session_factory: Any,
) -> Any:
    """Create a StravaSyncService with an authenticated API client.

    Args:
        user_id: Internal user ID.
        auth_data: Dict with encrypted_access_token and encrypted_refresh_token.
        worker_settings: Strava worker settings (contains encryption key, client creds).

    Returns:
        Ready-to-use StravaSyncService.
    """
    from strava_sync_service import StravaSyncService

    return StravaSyncService(
        api_client=_create_api_client(
            user_id, auth_data, worker_settings, session_factory
        ),
        user_id=user_id,
    )


def _create_api_client(
    user_id: str,
    auth_data: dict[str, Any],
    worker_settings: StravaSettings,
    session_factory: Any,
) -> Any:
    """Create a StravaAPIClient authenticated as the user.

    Args:
        user_id: Internal user ID.
        auth_data: Dict with encrypted_access_token and encrypted_refresh_token.
        worker_settings: Strava worker settings (contains encryption key, client creds).
        session_factory: Session factory used to persist refreshed tokens.

    Returns:
        Ready-to-use StravaAPIClient.
    """
    from strava_api_client import StravaAPIClient
    from strava_auth_service import StravaAuthService

    auth_service = StravaAuthService(
        encryption_key=worker_settings.encryption_key.get_secret_value(),
        client_id=worker_settings.strava_client_id,
        client_secret=worker_settings.strava_client_secret.get_secret_value(),
    )

    access_token = auth_service.decrypt(auth_data["encrypted_access_token"])
    refresh_token = auth_service.decrypt(auth_data["encrypted_refresh_token"])

    async def on_token_refresh(tokens: Any) -> None:
        await _update_user_tokens(session_factory, user_id, tokens, auth_service)

    return StravaAPIClient(
        access_token=access_token,
        refresh_token_value=refresh_token,
        auth_service=auth_service,
        on_token_refresh=on_token_refresh,
    )


# ---------------------------------------------------------------------------
# Non-blocking fan-out helpers
#
# The worker-agnostic pieces (`persist_fanout_children`, `record_child_terminal`,
# `is_final_attempt`) live in `core_shared.fanout` and are imported above. The
# helpers below are Strava-specific: it owns its parent row up-front
# (`_ensure_parent_row`) since nothing enqueues one ahead of the orchestrator,
# and its batch sync manages its own per-activity transactions, so the child
# terminal updates run in their own committed unit of work.
# ---------------------------------------------------------------------------


async def _ensure_parent_row(
    repo: SyncJobRepository,
    *,
    job_id: str,
    user_id: str,
    sync_type: str,
    started_at: datetime,
) -> None:
    """Idempotently own the orchestrator's parent ``sync_jobs`` row.

    The orchestrator's own ``job_id`` is the parent. On the first run no row
    exists yet (nothing enqueues a row for Strava), so create it; on an ARQ
    retry it already exists. Either way mark it ``running`` with ``started_at``
    before the children are persisted.
    """
    existing = await repo.get_by_job_id(job_id)
    if existing is None:
        await repo.create(
            job_id=job_id,
            user_id=user_id,
            integration_source="strava",
            sync_type=sync_type,
            status="running",
        )
    await repo.update_status(
        job_id=job_id, status="running", started_at=started_at, progress=0
    )


async def _record_child_completion(
    session_factory: Any,
    child_job_id: str,
    parent_job_id: str,
) -> None:
    """Mark a child row ``completed`` and bump ``completed_children``.

    Runs in its own committed unit of work because the Strava batch sync owns its
    per-activity transactions internally, so there is no shared session to join.
    """
    async with session_factory() as session:
        conn = await session.connection()
        repo = SyncJobRepository(conn)
        await _record_child_terminal(
            repo,
            child_job_id=child_job_id,
            parent_job_id=parent_job_id,
            status="completed",
        )
        await session.commit()


async def _record_child_failure(
    session_factory: Any,
    child_job_id: str,
    parent_job_id: str | None,
    error_message: str,
) -> None:
    """Mark a child row ``failed`` and bump the parent's ``failed_children``.

    A no-op without a ``parent_job_id`` (legacy/direct invocation has no row).
    """
    if not parent_job_id:
        return
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


@trace_arq_job
async def process_strava_webhook_event(
    ctx: dict[str, Any],
    event_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Process a Strava webhook event.

    Dispatches to the appropriate handler based on the event's
    ``aspect_type`` (create, update, delete) and ``object_type``.

    Args:
        ctx: ARQ worker context (contains session_factory, settings).
        event_data: Webhook event payload with keys:
            - aspect_type: "create", "update", or "delete"
            - object_type: "activity" or "athlete"
            - object_id: Strava object ID
            - owner_id: Strava athlete ID
            - subscription_id: Webhook subscription ID
            - event_time: Unix timestamp
            - updates: Optional dict of updated fields

    Returns:
        Dict with processing result status.
    """
    aspect_type = event_data.get("aspect_type", "unknown")
    object_type = event_data.get("object_type", "unknown")
    object_id = event_data.get("object_id")
    owner_id = event_data.get("owner_id")

    if object_type != "activity":
        logger.debug(
            "Ignoring non-activity webhook event in worker",
            object_type=object_type,
            aspect_type=aspect_type,
            owner_id=owner_id,
        )
        return {"status": "ignored", "reason": f"object_type={object_type}"}

    logger.info(
        "Processing Strava webhook event",
        aspect_type=aspect_type,
        object_type=object_type,
        object_id=object_id,
        owner_id=owner_id,
    )

    session_factory = ctx["session_factory"]
    worker_settings: StravaSettings = ctx["settings"]

    if owner_id is None:
        logger.warning(
            "Webhook event missing owner_id",
            object_id=object_id,
            aspect_type=aspect_type,
        )
        return {"status": "skipped", "reason": "missing_owner_id"}

    if object_id is None or not isinstance(object_id, int):
        logger.warning(
            "Webhook event missing or invalid object_id",
            object_id=object_id,
            aspect_type=aspect_type,
            owner_id=owner_id,
        )
        return {"status": "skipped", "reason": "invalid_object_id"}

    # Resolve the user from the athlete_id
    user_info = await _resolve_user_for_athlete(session_factory, int(owner_id))
    if user_info is None:
        logger.warning(
            "No user found for Strava athlete_id",
            owner_id=owner_id,
            object_id=object_id,
        )
        return {"status": "skipped", "reason": "unknown_athlete"}

    user_id, auth_data = user_info

    if aspect_type in ("create", "update"):
        sync_service = _create_sync_service(
            user_id, auth_data, worker_settings, session_factory
        )
        try:
            async with session_factory() as session:
                async with session.begin():
                    events = await sync_service.sync_single_activity(
                        activity_id=object_id, session=session
                    )
                    logger.info(
                        "Webhook activity sync complete",
                        aspect_type=aspect_type,
                        object_id=object_id,
                        events_created=len(events),
                    )
                    return {
                        "status": "processed",
                        "aspect_type": aspect_type,
                        "object_id": object_id,
                        "events_created": len(events),
                    }
        except StravaRateLimitError as exc:
            defer = _rate_limit_defer(exc)
            logger.warning(
                "Rate limit reached in webhook event, retrying",
                retry_after=exc.retry_after,
                defer_seconds=defer,
            )
            raise Retry(defer=defer) from exc
        finally:
            await sync_service._api_client.close()

    elif aspect_type == "delete":
        sync_service = _create_sync_service(
            user_id, auth_data, worker_settings, session_factory
        )
        try:
            async with session_factory() as session:
                async with session.begin():
                    event = await sync_service.handle_delete(
                        activity_id=object_id, session=session
                    )
                    logger.info(
                        "Webhook delete handled",
                        object_id=object_id,
                        event_created=event is not None,
                    )
                    return {
                        "status": "processed",
                        "aspect_type": "delete",
                        "object_id": object_id,
                        "event_created": event is not None,
                    }
        except StravaRateLimitError as exc:
            defer = _rate_limit_defer(exc)
            logger.warning(
                "Rate limit reached in webhook delete, retrying",
                retry_after=exc.retry_after,
                defer_seconds=defer,
            )
            raise Retry(defer=defer) from exc
        finally:
            await sync_service._api_client.close()

    else:
        logger.warning(
            "Unknown Strava webhook aspect_type",
            aspect_type=aspect_type,
            object_id=object_id,
        )
        return {"status": "ignored", "reason": f"unknown aspect_type={aspect_type}"}


@trace_arq_job
async def sync_strava_activities(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """
    ARQ task: orchestrate Strava activity sync (non-blocking fan-out).

    Drains the activity-page generator, owns the parent ``sync_jobs`` row
    (its ``ctx['job_id']``), persists one linked child row per page, sets
    ``expected_children``, marks the parent ``in_progress`` and returns
    immediately — it never awaits the children. The shared reconciliation cron
    finalises the parent (``completed``/``failed``) against the child rows. Each
    child batch commits independently and updates its own row + the parent
    counters.

    Called when the user clicks "Import Activities" in the UI or when a full
    sync is triggered programmatically.

    Args:
        ctx: ARQ worker context (must contain ``redis``, ``session_factory``).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dict with orchestration summary.
    """
    worker_settings: StravaSettings = ctx["settings"]
    session_factory = ctx["session_factory"]
    job_id = ctx.get("job_id", "unknown")
    started_at = datetime.now(UTC)

    logger.info(
        "Starting Strava activity sync orchestrator",
        user_id=user_id,
        sync_type=sync_type,
        job_id=job_id,
    )

    auth_data = await _resolve_user_by_id(session_factory, user_id)
    if auth_data is None:
        logger.error(
            "No Strava auth found for user",
            user_id=user_id,
        )
        return {"status": "error", "reason": "no_auth"}

    # Own the parent row up-front — before draining — so the integrations
    # dashboard shows an in-flight sync immediately, even if the drain defers on
    # a rate limit (the ARQ retry then re-runs against an already-running row).
    async with session_factory() as session:
        conn = await session.connection()
        repo = SyncJobRepository(conn)
        await _ensure_parent_row(
            repo,
            job_id=job_id,
            user_id=user_id,
            sync_type=sync_type,
            started_at=started_at,
        )
        await session.commit()

    sync_service = _create_sync_service(
        user_id, auth_data, worker_settings, session_factory
    )

    try:
        # For smart sync, we could use after_timestamp from last sync.
        # For now, full sync imports everything.
        after_ts = None

        # Drain every page into memory first so the child count is known before
        # we persist the hierarchy (persist-then-dispatch).
        batches: list[list[int]] = [
            activity_ids
            async for activity_ids in sync_service.list_activity_batches(
                after_timestamp=after_ts,
            )
        ]

        async with session_factory() as session:
            conn = await session.connection()
            repo = SyncJobRepository(conn)
            child_ids = await _persist_fanout_children(
                repo,
                parent_job_id=job_id,
                user_id=user_id,
                integration_source="strava",
                sync_type=sync_type,
                child_id_prefix=f"strava-batch-{job_id}-p",
                count=len(batches),
            )
            await session.commit()

        # Child rows + parent state are committed; dispatch is now safe.
        dispatched = 0
        for child_id, activity_ids in zip(child_ids, batches, strict=True):
            job = await ctx["redis"].enqueue_job(
                "sync_strava_activity_batch",
                user_id,
                activity_ids,
                job_id,
                _job_id=child_id,
                _queue_name=STRAVA_ARQ_QUEUE_NAME,
            )
            if job is None:
                # Deterministic _job_id means a prior run already enqueued this
                # child; the child row still exists, so the reconciler stays
                # correct. Surface it rather than silently over-reporting.
                logger.warning(
                    "Strava activity batch already enqueued; skipping",
                    job_id=job_id,
                    child_job_id=child_id,
                )
            else:
                dispatched += 1

        logger.info(
            "Strava sync orchestrator dispatched",
            user_id=user_id,
            job_id=job_id,
            expected_children=len(batches),
            dispatched=dispatched,
        )
        return {
            "status": "in_progress" if batches else "completed",
            "sync_type": sync_type,
            "batches_enqueued": len(batches),
        }
    except StravaRateLimitError as exc:
        defer = _rate_limit_defer(exc)
        logger.warning(
            "Rate limit reached in orchestrator, retrying",
            retry_after=exc.retry_after,
            defer_seconds=defer,
        )
        raise Retry(defer=defer) from exc
    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_strava_activity_batch(
    ctx: dict[str, Any],
    user_id: str,
    activity_ids: list[int],
    parent_job_id: str | None = None,
) -> dict[str, Any]:
    """
    ARQ task: process a batch of Strava activity IDs.

    Fetches full activity details + streams from Strava and creates outbox
    events. Each activity is processed independently so one failure doesn't
    block others.

    On success the batch marks **its own** child ``sync_jobs`` row ``completed``
    and atomically increments the parent's ``completed_children``. ARQ retries
    only a ``Retry``, so any other failure — missing auth, a sync service that
    cannot be built, or the sync raising — marks the row ``failed`` and
    increments ``failed_children`` on this attempt. A rate limit raises ``Retry``
    without touching the counters until the final attempt, where it records the
    failure instead (ARQ would drop a ``Retry`` raised then without running the
    job again). ``parent_job_id`` is optional so legacy/direct invocations still
    work (counters are skipped).

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        activity_ids: Strava activity IDs to process.
        parent_job_id: Orchestrator job id for child-row + counter bookkeeping.

    Returns:
        Dict with batch processing result.
    """
    session_factory = ctx["session_factory"]
    worker_settings: StravaSettings = ctx["settings"]
    child_job_id = ctx.get("job_id", "unknown")

    logger.info(
        "Processing Strava activity batch",
        user_id=user_id,
        batch_size=len(activity_ids),
        parent_job_id=parent_job_id,
    )

    try:
        auth_data = await _resolve_user_by_id(session_factory, user_id)
        sync_service = (
            _create_sync_service(user_id, auth_data, worker_settings, session_factory)
            if auth_data is not None
            else None
        )
    except Exception as e:
        logger.exception(
            "Strava activity batch setup failed", user_id=user_id, error=str(e)
        )
        await _record_child_failure(
            session_factory, child_job_id, parent_job_id, str(e)
        )
        raise

    if sync_service is None:
        no_auth = "No Strava auth found for user"
        logger.error(no_auth, user_id=user_id)
        await _record_child_failure(
            session_factory, child_job_id, parent_job_id, no_auth
        )
        return {"status": "error", "reason": "no_auth"}

    try:
        result = await sync_service.sync_activity_batch(
            activity_ids=activity_ids,
            session_factory=session_factory,
        )

        if parent_job_id:
            await _record_child_completion(session_factory, child_job_id, parent_job_id)

        logger.info(
            "Strava activity batch completed",
            user_id=user_id,
            **result,
        )
        return {
            "status": "completed",
            **result,
        }
    except StravaRateLimitError as exc:
        if not _is_final_attempt(ctx, max_tries=STRAVA_MAX_TRIES):
            # Transient: ARQ retries without recording a terminal child row.
            defer = _rate_limit_defer(exc)
            logger.warning(
                "Rate limit reached in batch sync, retrying",
                retry_after=exc.retry_after,
                defer_seconds=defer,
            )
            raise Retry(defer=defer) from exc
        logger.exception(
            "Strava activity batch still rate limited on its final attempt",
            user_id=user_id,
            error=str(exc),
        )
        await _record_child_failure(
            session_factory, child_job_id, parent_job_id, str(exc)
        )
        raise
    except Exception as e:
        logger.exception("Strava activity batch failed", user_id=user_id, error=str(e))
        await _record_child_failure(
            session_factory, child_job_id, parent_job_id, str(e)
        )
        raise
    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def periodic_sync_all_strava_accounts(
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Periodic sync wrapper that syncs all active Strava accounts.

    This function is called by ARQ cron jobs and enqueues individual
    ``sync_strava_activities`` tasks for each connected Strava
    integration using 'smart' sync type.

    Args:
        ctx: ARQ context dictionary containing Redis pool and session_factory.

    Returns:
        Dictionary with sync summary (accounts_found, jobs_enqueued, errors).
    """
    logger.info("Starting periodic sync for all Strava accounts")

    session_factory = ctx["session_factory"]

    accounts_found = 0
    jobs_enqueued = 0
    errors: list[str] = []

    try:
        async with session_factory() as session:
            from sqlalchemy import text

            stmt = text("""
                SELECT user_id, athlete_id
                FROM user_strava_auth
                ORDER BY user_id
            """)
            result = await session.execute(stmt)
            accounts = result.fetchall()

            accounts_found = len(accounts)
            logger.info(
                "Found active Strava accounts for periodic sync",
                accounts_count=accounts_found,
            )

            for row in accounts:
                user_id = row.user_id

                try:
                    job = await ctx["redis"].enqueue_job(
                        "sync_strava_activities",
                        str(user_id),
                        "smart",
                        _queue_name=STRAVA_ARQ_QUEUE_NAME,
                    )

                    if job:
                        jobs_enqueued += 1
                        logger.info(
                            "Enqueued periodic Strava sync job",
                            job_id=job.job_id,
                            user_id=user_id,
                        )
                    else:
                        error_msg = f"Failed to enqueue Strava sync for user {user_id}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic Strava sync job",
                            user_id=user_id,
                        )

                except Exception as e:  # noqa: BLE001
                    error_msg = (
                        f"Error enqueueing Strava sync for user {user_id}: {e!s}"
                    )
                    errors.append(error_msg)
                    logger.error(
                        "Error enqueueing periodic Strava sync job",
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

        logger.info(
            "Periodic Strava sync scheduling complete",
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
            "Fatal error during periodic Strava sync",
            accounts_found=accounts_found,
            jobs_enqueued=jobs_enqueued,
            exc_info=True,
        )
        raise


# One-off backfill of fitness durations from moving to elapsed time. A long
# history pages slowly under the rate limiter, so it gets more than arq's
# default 300s job timeout.
DURATION_BACKFILL_TIMEOUT_S = 1800


def duration_backfill_marker(user_id: str) -> str:
    """Redis key recording that the user's duration backfill has completed.

    Delete it to have the next worker startup run the backfill again; a rerun
    is harmless, as an already-corrected duration matches no expected value.
    """
    return f"strava:backfill:elapsed_duration:v1:{user_id}"


@trace_arq_job
async def backfill_strava_elapsed_durations(
    ctx: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """
    ARQ task: correct the user's synced Strava durations to elapsed time.

    Lists every activity and emits a compare-and-set correction for each
    Strava journal (see ``duration_backfill``); the backend leaves any
    duration the user has edited alone. On success records the user's marker
    so the startup hook does not enqueue it again. A rate limit defers the
    whole job: nothing is written until every page has been listed.

    Args:
        ctx: ARQ worker context (``redis``, ``session_factory``, ``settings``).
        user_id: Internal user ID.

    Returns:
        Dict with the backfill status and counts.
    """
    from duration_backfill import StravaDurationBackfillService

    session_factory = ctx["session_factory"]
    worker_settings: StravaSettings = ctx["settings"]

    auth_data = await _resolve_user_by_id(session_factory, user_id)
    if auth_data is None:
        logger.error("No Strava auth found for duration backfill", user_id=user_id)
        return {"status": "error", "reason": "no_auth"}

    api_client = _create_api_client(
        user_id, auth_data, worker_settings, session_factory
    )
    try:
        counts = await StravaDurationBackfillService(
            api_client=api_client, user_id=user_id
        ).run(session_factory)
    except StravaRateLimitError as exc:
        defer = _rate_limit_defer(exc)
        logger.warning(
            "Rate limit reached in duration backfill, retrying",
            user_id=user_id,
            defer_seconds=defer,
        )
        raise Retry(defer=defer) from exc
    finally:
        await api_client.close()

    await ctx["redis"].set(
        duration_backfill_marker(user_id), datetime.now(UTC).isoformat()
    )
    return {"status": "completed", **counts}


async def _run_stream_consumer(session_factory: Any, worker_settings: Any) -> None:
    """Adapt the Strava stream consumer to the shared lifecycle factory's shape.

    ``build_worker_lifecycle`` calls ``consumer_factory(session_factory, settings)``;
    ``run_strava_stream_consumer`` takes ``redis_url``/``stream_name`` keywords, so
    this thin closure reads them off the worker settings.
    """
    from stream_consumer_tasks import run_strava_stream_consumer

    await run_strava_stream_consumer(
        session_factory=session_factory,
        redis_url=worker_settings.redis_url,
        stream_name=worker_settings.stream_name,
    )


# Shared lifecycle: build the database session factory, launch the stream
# consumer, and on shutdown cancel/reap it. Strava logs consumer errors in real
# time (done-callback) and does not close the session factory on shutdown.
_on_startup, _on_shutdown = build_worker_lifecycle(
    settings=settings,
    consumer_factory=_run_stream_consumer,
    close_session_factory=False,
    log_consumer_errors=True,
)


async def _enqueue_duration_backfills(ctx: dict[str, Any]) -> None:
    """Enqueue the duration backfill for each user whose marker is unset.

    The deterministic job id keeps a restart from queueing a second copy
    while one is pending. Best-effort: a failure is logged and the worker
    starts regardless, retrying on its next startup.
    """
    from sqlalchemy import text

    try:
        async with ctx["session_factory"]() as session:
            result = await session.execute(
                text("SELECT user_id FROM user_strava_auth ORDER BY user_id")
            )
            user_ids = [str(row.user_id) for row in result.fetchall()]

        for user_id in user_ids:
            if await ctx["redis"].exists(duration_backfill_marker(user_id)):
                continue
            await ctx["redis"].enqueue_job(
                "backfill_strava_elapsed_durations",
                user_id,
                _job_id=f"strava-duration-backfill-v1-{user_id}",
                _queue_name=STRAVA_ARQ_QUEUE_NAME,
            )
            logger.info("Enqueued Strava duration backfill", user_id=user_id)
    except Exception:
        logger.exception("Failed to enqueue Strava duration backfills")


async def _on_startup_with_backfill(ctx: dict[str, Any]) -> None:
    """Shared startup (session factory, stream consumer), then the backfill."""
    await _on_startup(ctx)
    await _enqueue_duration_backfills(ctx)


# ARQ Worker Settings
class StravaWorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    """ARQ worker configuration.

    Operational defaults (``job_timeout``, ``keep_result``, retry backoff) come from
    :class:`core_shared.SharedARQWorkerSettings` and equal arq's own constructor
    defaults, so they apply unchanged. ``health_check_interval`` is the exception:
    arq's ``get_kwargs`` reads only this leaf class's attributes, so the inherited
    shared ``30`` is invisible to arq and it falls back to arq's default of ``3600``
    (this worker does not redeclare it). Only the functions list, consumer wiring,
    and documented overrides live here.
    """

    # Task functions
    functions = [
        process_strava_webhook_event,
        sync_strava_activities,
        sync_strava_activity_batch,
        periodic_sync_all_strava_accounts,
        reconcile_in_progress_parents,
        func(
            backfill_strava_elapsed_durations,
            timeout=DURATION_BACKFILL_TIMEOUT_S,
        ),
    ]

    # Worker lifecycle (shared factory). Cast to arq's StartupShutdown Protocol:
    # the hooks accept ``ctx`` but the shared LifecycleHook alias is a plain
    # positional Callable, which the Protocol's named-parameter form rejects.
    on_startup: StartupShutdown = cast("StartupShutdown", _on_startup_with_backfill)
    on_shutdown: StartupShutdown = cast("StartupShutdown", _on_shutdown)

    # Redis settings (shared helper).
    redis_settings = redis_settings_from_url(settings.redis_url)

    # Queue name.
    queue_name = STRAVA_ARQ_QUEUE_NAME

    # Documented overrides:
    # - max_tries=STRAVA_MAX_TRIES: Strava's rate limits require many retries to
    #   reach the daily-limit reset (~20 hours of hourly deferrals).
    # - max_jobs=5: cap concurrency below arq's default of 10 to stay within
    #   Strava's API rate budget.
    max_tries = STRAVA_MAX_TRIES
    max_jobs = 5

    # Cron schedule: the periodic-sync cron (shared helper; empty when periodic
    # sync is disabled) plus the always-on fan-out reconciliation cron, which
    # finalises non-blocking ``IN_PROGRESS`` parents against their child rows.
    cron_jobs = [
        *generate_cron_jobs(
            periodic_sync_all_strava_accounts,
            enable_periodic_sync=settings.enable_periodic_sync,
            sync_interval_hours=settings.sync_interval_hours,
        ),
        *generate_reconciliation_cron(reconcile_in_progress_parents),
    ]


if __name__ == "__main__":
    # Setup OpenTelemetry
    setup_telemetry(settings)

    # Run the worker
    logger.info("Starting Strava ARQ worker", worker_id=settings.worker_id)
    run_worker(StravaWorkerSettings)
