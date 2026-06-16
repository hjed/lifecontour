"""
Shared ARQ worker toolkit for integration workers.

Consolidates the ARQ configuration that every integration worker hand-wrote and
that had drifted apart:

* **Operational defaults** — :class:`SharedARQWorkerSettings` carries the
  standard ``job_timeout``/``keep_result``/``max_tries``/``health_check_interval``
  and the :func:`default_retry_delay` backoff as class attributes. A worker
  subclasses it and *overrides a default only by redeclaring that attribute*,
  with a documented reason (e.g. google ``job_timeout=600``, strava
  ``max_tries=20``).
* **Cron generation** — :func:`generate_cron_jobs` turns ``enable_periodic_sync``
  + ``sync_interval_hours`` into the ARQ cron list, replacing the duplicated
  ``immich._generate_cron_jobs`` and the inline google/strava blocks.
* **Lifecycle** — :func:`build_worker_lifecycle` builds the ``on_startup`` /
  ``on_shutdown`` pair that creates the database session factory, stores it (and
  the settings) in the ARQ context, launches the worker's stream-consumer
  coroutine as a task, and on shutdown cancels that task and optionally closes
  the session factory. It folds in the per-worker variants as options
  (``log_consumer_errors`` mirrors strava's done-callback;
  ``close_session_factory`` mirrors google's cleanup).

This module is additive (ITER14-002 Phase 1): nothing consumes it yet. The
per-worker migrations that adopt it — and delete the duplicated
``_parse_redis_url`` / ``_generate_cron_jobs`` / startup-shutdown code — land in
ITER14-002 Phases 2 (google + strava) and 3 (immich + snipeit).

As with :mod:`core_shared.worker_settings`, ``arq`` is **not** a hard runtime
dependency of ``core_shared`` (it pins ``redis<6`` against our ``redis>=8``), so
the only ``arq``-dependent helper, :func:`generate_cron_jobs`, imports it lazily.
The defaults class and the lifecycle factory need no ``arq`` import, keeping
``import core_shared`` working without it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from core_shared.database.engine import create_session_factory
from core_shared.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from core_shared.worker_settings import BaseWorkerSettings

logger = get_logger(__name__)

# Standard ARQ operational defaults. These are the canonical values shared by
# all workers; a worker overrides one only with a documented reason.
DEFAULT_JOB_TIMEOUT = 300  # seconds — hard cap on a single job's runtime
DEFAULT_KEEP_RESULT = 3600  # seconds — how long job results are retained
DEFAULT_MAX_TRIES = 5  # attempts before a job is dead-lettered
DEFAULT_HEALTH_CHECK_INTERVAL = 30  # seconds between ARQ health-check writes

# An ARQ startup/shutdown hook: an async callable taking the worker ``ctx`` dict.
LifecycleHook = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# Builds the worker's stream-consumer coroutine from the session factory and
# settings. Workers wrap their ``run_<worker>_stream_consumer(...)`` in a closure
# of this shape so the factory does not need to know per-worker arguments (some
# consumers take ``stream_name``, some do not).
ConsumerFactory = Callable[
    ["async_sessionmaker[AsyncSession]", "BaseWorkerSettings"],
    Coroutine[Any, Any, None],
]


def default_retry_delay(retry_count: int) -> float:
    """Exponential backoff with ±20% jitter, capped at 15 minutes.

    Ported from the google worker's ``retry_delay_func`` so the shared toolkit
    reproduces its behaviour:

    * retry 0 → ~60s (48–72s), retry 1 → ~120s, retry 2 → ~240s, retry 3 → ~480s
    * retry 4+ → capped at 900s

    Jitter is intentionally random to avoid a thundering herd; tests assert the
    bounds rather than an exact value.
    """
    base_delay = 60
    delay = base_delay * (2**retry_count)

    import secrets

    jitter = secrets.SystemRandom().uniform(0.8, 1.2)
    delay_with_jitter = delay * jitter

    return float(min(delay_with_jitter, 900.0))


class SharedARQWorkerSettings:
    """Base carrying the shared ARQ operational defaults as class attributes.

    A worker's ARQ ``WorkerSettings`` subclasses this and declares only its
    ``functions`` list, its redis settings, its lifecycle hooks, its cron jobs,
    and any genuinely integration-specific override (redeclaring the attribute).

    It deliberately does **not** inherit arq's own ``WorkerSettingsBase`` so that
    importing ``core_shared`` never imports ``arq`` (subclassing arq's base is
    optional — it only provides typing).
    """

    job_timeout: int = DEFAULT_JOB_TIMEOUT
    keep_result: int = DEFAULT_KEEP_RESULT
    max_tries: int = DEFAULT_MAX_TRIES
    health_check_interval: int = DEFAULT_HEALTH_CHECK_INTERVAL
    retry_delay = staticmethod(default_retry_delay)


def generate_cron_jobs(
    func: Any,
    *,
    enable_periodic_sync: bool,
    sync_interval_hours: int,
    minute: int = 0,
    unique: bool = True,
) -> list[Any]:
    """Build the ARQ cron list for a worker's periodic-sync function.

    Returns an empty list when periodic sync is disabled. Otherwise the function
    is scheduled at the top of every ``sync_interval_hours``-th hour (e.g.
    ``sync_interval_hours=6`` → hours ``{0, 6, 12, 18}``), matching the schedule
    the immich/google/strava workers produced by hand. ``sync_interval_hours`` is
    floored at 1 to avoid a zero step, mirroring ``immich._generate_cron_jobs``.

    ``arq`` is imported lazily so importing ``core_shared`` does not require it
    (see the module docstring); workers that schedule cron jobs always depend on
    ``arq``.
    """
    if not enable_periodic_sync:
        return []

    interval = max(1, sync_interval_hours)
    sync_hours = set(range(0, 24, interval))

    from arq import cron

    logger.info(
        "Periodic sync enabled",
        sync_interval_hours=interval,
        sync_hours=sorted(sync_hours),
    )

    return [
        cron(
            func,
            hour=sync_hours,
            minute=minute,
            unique=unique,
        )
    ]


def _log_consumer_task_done(task: asyncio.Task[None]) -> None:
    """Log unhandled exceptions from the stream-consumer background task.

    Attached as a done-callback when ``log_consumer_errors`` is set. Without it,
    a consumer that raises has its exception swallowed and the worker silently
    runs degraded. Ported from strava's ``_on_consumer_task_done``.
    """
    if task.cancelled():
        logger.info("Stream consumer task was cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Stream consumer task failed unexpectedly",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=exc,
        )


async def _cancel_consumer_task(task: asyncio.Task[None] | None) -> None:
    """Cancel (if still running) and reap the stream-consumer task on shutdown.

    Uses ``asyncio.gather(..., return_exceptions=True)`` so the task's own
    ``CancelledError`` is captured as a result rather than caught in an
    ``except`` clause — if ``on_shutdown`` itself is being cancelled the await
    still propagates that, which is the correct behaviour. An already-completed
    task is reaped too: its result is retrieved (avoiding an unretrieved-exception
    warning) and a failure is logged, so a consumer that crashed mid-run is
    surfaced at shutdown rather than swallowed.
    """
    if task is None:
        return

    if not task.done():
        task.cancel()

    result = (await asyncio.gather(task, return_exceptions=True))[0]
    if isinstance(result, asyncio.CancelledError):
        logger.info("Stream consumer task stopped")
    elif isinstance(result, BaseException):
        logger.error(
            "Stream consumer task failed during shutdown",
            error=str(result),
            error_type=type(result).__name__,
            exc_info=result,
        )


async def _close_session_factory(session_factory: Any) -> None:
    """Dispose the session factory's engine (and connection pool) on shutdown.

    ``create_session_factory`` returns an ``async_sessionmaker``, which has no
    ``close`` of its own — the connection pool lives on the bound ``AsyncEngine``
    — so disposing that engine is what actually releases the pool. A direct
    ``close`` coroutine is honoured first for factories (or test doubles) that
    expose one.
    """
    if session_factory is None:
        return

    close = getattr(session_factory, "close", None)
    if close is not None:
        await close()
        return

    engine = getattr(session_factory, "kw", {}).get("bind")
    dispose = getattr(engine, "dispose", None)
    if dispose is not None:
        await dispose()


def build_worker_lifecycle(
    *,
    settings: BaseWorkerSettings,
    consumer_factory: ConsumerFactory,
    close_session_factory: bool = False,
    log_consumer_errors: bool = False,
) -> tuple[LifecycleHook, LifecycleHook]:
    """Build the shared ``on_startup`` / ``on_shutdown`` ARQ lifecycle hooks.

    ``on_startup`` creates the database session factory from
    ``settings.database_url``, stores it and ``settings`` in the ARQ ``ctx``,
    launches ``consumer_factory(session_factory, settings)`` as a background
    task, and stores that task in ``ctx``. ``on_shutdown`` cancels and reaps the
    consumer task (surfacing a crash, handling ``CancelledError``) and, when
    ``close_session_factory`` is set, disposes the session factory's engine.

    Args:
        settings: The worker's settings (provides the database URL and is stored
            in ``ctx`` for tasks to read).
        consumer_factory: Builds the stream-consumer coroutine to run as a task.
        close_session_factory: Dispose the session factory's engine/pool on
            shutdown (google).
        log_consumer_errors: Attach a done-callback that logs unhandled consumer
            exceptions in real time, i.e. as soon as the task fails rather than
            only at shutdown (strava).

    Returns:
        ``(on_startup, on_shutdown)`` — the pair to assign to the worker's ARQ
        ``WorkerSettings``.
    """

    async def on_startup(ctx: dict[str, Any]) -> None:
        logger.info("Worker starting up", worker_id=settings.worker_id)

        session_factory = create_session_factory(
            settings.database_url.get_secret_value()
        )
        ctx["session_factory"] = session_factory
        ctx["settings"] = settings

        consumer_task: asyncio.Task[None] = asyncio.create_task(
            consumer_factory(session_factory, settings)
        )
        if log_consumer_errors:
            consumer_task.add_done_callback(_log_consumer_task_done)
        ctx["stream_consumer_task"] = consumer_task

        logger.info("Worker startup complete", worker_id=settings.worker_id)

    async def on_shutdown(ctx: dict[str, Any]) -> None:
        logger.info("Worker shutting down", worker_id=settings.worker_id)

        await _cancel_consumer_task(ctx.get("stream_consumer_task"))
        if close_session_factory:
            await _close_session_factory(ctx.get("session_factory"))

        logger.info("Worker shutdown complete", worker_id=settings.worker_id)

    return on_startup, on_shutdown
