"""
Unit tests for the shared ARQ worker toolkit.

Covers ITER14-002 Phase 1: the shared ARQ operational defaults
(``SharedARQWorkerSettings`` + ``default_retry_delay``), the cron-generation
helper (``generate_cron_jobs``), and the ``on_startup``/``on_shutdown``
lifecycle factory (``build_worker_lifecycle``). All three are additive
``core_shared`` library code, not yet consumed by any worker; the per-worker
migrations that wire them in (and delete the duplicated ``_parse_redis_url`` /
``_generate_cron_jobs`` / startup-shutdown code) land in ITER14-002 Phases 2/3.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from arq import cron
from pydantic import SecretStr

from core_shared import worker_arq
from core_shared.worker_arq import (
    DEFAULT_HEALTH_CHECK_INTERVAL,
    DEFAULT_JOB_TIMEOUT,
    DEFAULT_KEEP_RESULT,
    DEFAULT_MAX_TRIES,
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    default_retry_delay,
    generate_cron_jobs,
)
from core_shared.worker_settings import BaseWorkerSettings

_DB_URL = "postgresql://user:pw@dbhost:5432/pms"


def _make_settings(**overrides: Any) -> BaseWorkerSettings:
    """Build a minimal ``BaseWorkerSettings`` without touching a local ``.env``."""
    kwargs: dict[str, Any] = {"database_url": SecretStr(_DB_URL), "_env_file": None}
    kwargs.update(overrides)
    return BaseWorkerSettings(**kwargs)


# ---------------------------------------------------------------------------
# Shared ARQ operational defaults + override
# ---------------------------------------------------------------------------


class TestSharedARQDefaults:
    """The shared defaults are defined once and overridable by redeclaration."""

    def test_default_constants(self) -> None:
        """The documented default values match the canonical worker config."""
        assert DEFAULT_JOB_TIMEOUT == 300
        assert DEFAULT_KEEP_RESULT == 3600
        assert DEFAULT_MAX_TRIES == 5
        assert DEFAULT_HEALTH_CHECK_INTERVAL == 30

    def test_base_class_exposes_defaults(self) -> None:
        """``SharedARQWorkerSettings`` carries the defaults as class attributes."""
        assert SharedARQWorkerSettings.job_timeout == DEFAULT_JOB_TIMEOUT
        assert SharedARQWorkerSettings.keep_result == DEFAULT_KEEP_RESULT
        assert SharedARQWorkerSettings.max_tries == DEFAULT_MAX_TRIES
        assert (
            SharedARQWorkerSettings.health_check_interval
            == DEFAULT_HEALTH_CHECK_INTERVAL
        )

    def test_retry_delay_is_default_function(self) -> None:
        """The retry delay defaults to the shared backoff function."""
        # Access via the class so the staticmethod is unwrapped to the function.
        assert SharedARQWorkerSettings.retry_delay is default_retry_delay

    def test_subclass_inherits_defaults(self) -> None:
        """A subclass with no overrides inherits every default."""

        class WorkerSettings(SharedARQWorkerSettings):
            functions: list[Any] = []

        assert WorkerSettings.job_timeout == DEFAULT_JOB_TIMEOUT
        assert WorkerSettings.max_tries == DEFAULT_MAX_TRIES
        assert WorkerSettings.keep_result == DEFAULT_KEEP_RESULT
        assert WorkerSettings.health_check_interval == DEFAULT_HEALTH_CHECK_INTERVAL

    def test_subclass_override_replaces_default(self) -> None:
        """Redeclaring an attribute overrides only that default (the documented
        override mechanism), preserving the rest.

        Mirrors the behaviour-preserving overrides the P2/P3 migrations apply:
        google ``job_timeout=600`` and strava ``max_tries=20``.
        """

        class GoogleLike(SharedARQWorkerSettings):
            job_timeout = 600

        class StravaLike(SharedARQWorkerSettings):
            max_tries = 20

        assert GoogleLike.job_timeout == 600
        assert GoogleLike.max_tries == DEFAULT_MAX_TRIES  # untouched
        assert StravaLike.max_tries == 20
        assert StravaLike.job_timeout == DEFAULT_JOB_TIMEOUT  # untouched


class TestDefaultRetryDelay:
    """The shared exponential-backoff-with-jitter delay function."""

    @pytest.mark.parametrize(
        ("retry_count", "low", "high"),
        [
            (0, 48.0, 72.0),  # 60 * 0.8 .. 60 * 1.2
            (1, 96.0, 144.0),  # 120 * 0.8 .. 120 * 1.2
            (2, 192.0, 288.0),  # 240 * 0.8 .. 240 * 1.2
            (3, 384.0, 576.0),  # 480 * 0.8 .. 480 * 1.2
        ],
    )
    def test_within_jitter_bounds(
        self, retry_count: int, low: float, high: float
    ) -> None:
        """Each sample lands within the documented ±20% jitter window."""
        for _ in range(200):
            delay = default_retry_delay(retry_count)
            assert low <= delay <= high

    def test_capped_at_900_seconds(self) -> None:
        """High retry counts are capped at 900s (15 minutes)."""
        for _ in range(200):
            delay = default_retry_delay(10)
            assert 0 < delay <= 900.0

    def test_returns_float(self) -> None:
        """The delay is always a float."""
        assert isinstance(default_retry_delay(0), float)


# ---------------------------------------------------------------------------
# Cron-generation helper
# ---------------------------------------------------------------------------


async def _sample_periodic_job(ctx: dict[str, Any]) -> None:  # pragma: no cover
    """A stand-in periodic task to register on a cron schedule."""


def _legacy_generate_cron_jobs(
    enable_periodic_sync: bool, sync_interval_hours: int
) -> list[Any]:
    """The original immich ``_generate_cron_jobs``, used here as an oracle.

    Mirrors ``integration_workers/immich/worker.py`` so we can assert the shared
    helper is behaviour-preserving before that copy is deleted in Phase 3.
    """
    if not enable_periodic_sync:
        return []
    interval = max(1, sync_interval_hours)
    sync_hours = set(range(0, 24, interval))
    return [
        cron(
            _sample_periodic_job,
            hour=sync_hours,
            minute=0,
            unique=True,
        )
    ]


class TestGenerateCronJobs:
    """The shared cron helper reproduces the per-worker schedules exactly."""

    def test_disabled_returns_empty(self) -> None:
        """When periodic sync is disabled, no cron jobs are produced."""
        result = generate_cron_jobs(
            _sample_periodic_job,
            enable_periodic_sync=False,
            sync_interval_hours=6,
        )
        assert result == []

    @pytest.mark.parametrize(
        ("interval", "expected_hours"),
        [
            (6, {0, 6, 12, 18}),
            (24, {0}),
            (12, {0, 12}),
            (1, set(range(24))),
            (0, set(range(24))),  # 0 treated as 1 — no div-by-zero, runs hourly
        ],
    )
    def test_schedule_for_interval(
        self, interval: int, expected_hours: set[int]
    ) -> None:
        """The cron schedule fires at the expected hours for each interval."""
        result = generate_cron_jobs(
            _sample_periodic_job,
            enable_periodic_sync=True,
            sync_interval_hours=interval,
        )

        assert len(result) == 1
        job = result[0]
        assert set(job.hour) == expected_hours
        assert job.minute == 0
        assert job.unique is True
        assert job.coroutine is _sample_periodic_job

    @pytest.mark.parametrize("interval", [1, 6, 12, 24])
    def test_matches_legacy_immich_schedule(self, interval: int) -> None:
        """The helper is behaviour-equivalent to the legacy immich generator.

        Guards the Phase-3 deletion of ``immich._generate_cron_jobs``.
        """
        new = generate_cron_jobs(
            _sample_periodic_job,
            enable_periodic_sync=True,
            sync_interval_hours=interval,
        )
        old = _legacy_generate_cron_jobs(True, interval)

        assert len(new) == len(old) == 1
        assert set(new[0].hour) == set(old[0].hour)
        assert new[0].minute == old[0].minute
        assert new[0].unique == old[0].unique


# ---------------------------------------------------------------------------
# Lifecycle factory
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_session_factory(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Patch ``create_session_factory`` and return the mock factory it yields."""
    session_factory = Mock(name="session_factory")
    session_factory.close = AsyncMock()
    creator = Mock(name="create_session_factory", return_value=session_factory)
    monkeypatch.setattr(worker_arq, "create_session_factory", creator)
    # Expose the creator on the returned mock for call-arg assertions.
    session_factory._creator = creator
    return session_factory


@pytest.mark.asyncio
class TestBuildWorkerLifecycle:
    """The shared lifecycle factory builds matching on_startup/on_shutdown hooks."""

    async def test_startup_wires_ctx_keys(self, patched_session_factory: Mock) -> None:
        """on_startup stores the session factory, settings, and consumer task."""
        settings = _make_settings()
        started = asyncio.Event()

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            started.set()
            await asyncio.Event().wait()  # block until cancelled

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        await asyncio.wait_for(started.wait(), timeout=1)

        assert ctx["session_factory"] is patched_session_factory
        assert ctx["settings"] is settings
        assert isinstance(ctx["stream_consumer_task"], asyncio.Task)
        assert not ctx["stream_consumer_task"].done()

        # The session factory is built from the (unwrapped) database URL.
        patched_session_factory._creator.assert_called_once_with(_DB_URL)

        await on_shutdown(ctx)

    async def test_shutdown_cancels_consumer_task(
        self, patched_session_factory: Mock
    ) -> None:
        """on_shutdown cancels the consumer task and swallows CancelledError."""
        settings = _make_settings()

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            await asyncio.Event().wait()

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        task = ctx["stream_consumer_task"]

        await on_shutdown(ctx)  # must not raise

        assert task.cancelled()

    async def test_shutdown_handles_missing_task(
        self, patched_session_factory: Mock
    ) -> None:
        """on_shutdown is a no-op when no consumer task was launched."""
        settings = _make_settings()

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            await asyncio.sleep(0)

        _, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
        )

        await on_shutdown({})  # empty ctx — must not raise

    async def test_shutdown_handles_already_done_task(
        self, patched_session_factory: Mock
    ) -> None:
        """on_shutdown does not error when the consumer task already finished."""
        settings = _make_settings()

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            await asyncio.sleep(0)  # completes immediately

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        await ctx["stream_consumer_task"]  # let it finish (completes immediately)

        await on_shutdown(ctx)  # must not raise

    async def test_done_callback_logs_consumer_error(
        self, patched_session_factory: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With log_consumer_errors, a crashing consumer is logged via callback."""
        settings = _make_settings()
        mock_logger = Mock()
        monkeypatch.setattr(worker_arq, "logger", mock_logger)

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            raise RuntimeError("consumer boom")

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
            log_consumer_errors=True,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        # Let the task fail and the done-callback fire.
        with pytest.raises(RuntimeError):
            await ctx["stream_consumer_task"]
        await asyncio.sleep(0)  # allow the done-callback to run

        assert mock_logger.error.called
        await on_shutdown(ctx)

    async def test_failure_not_logged_in_real_time_then_surfaced_at_shutdown(
        self, patched_session_factory: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without log_consumer_errors there is no real-time callback, but a
        crashed consumer is still reaped and surfaced at shutdown — not swallowed.
        """
        settings = _make_settings()
        mock_logger = Mock()
        monkeypatch.setattr(worker_arq, "logger", mock_logger)

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            raise RuntimeError("consumer boom")

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
            log_consumer_errors=False,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        with pytest.raises(RuntimeError):
            await ctx["stream_consumer_task"]  # deterministically complete it
        await asyncio.sleep(0)  # allow any (absent) callback a chance to run

        # No done-callback was attached, so nothing is logged in real time.
        mock_logger.error.assert_not_called()

        # Shutdown reaps the already-failed task and surfaces the error.
        await on_shutdown(ctx)
        mock_logger.error.assert_called()

    async def test_shutdown_closes_session_factory_when_requested(
        self, patched_session_factory: Mock
    ) -> None:
        """With close_session_factory, shutdown awaits the factory's close()."""
        settings = _make_settings()

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            await asyncio.Event().wait()

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
            close_session_factory=True,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        await on_shutdown(ctx)

        patched_session_factory.close.assert_awaited_once()

    async def test_shutdown_does_not_close_by_default(
        self, patched_session_factory: Mock
    ) -> None:
        """By default the session factory is left open on shutdown."""
        settings = _make_settings()

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            await asyncio.Event().wait()

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        await on_shutdown(ctx)

        patched_session_factory.close.assert_not_called()

    async def test_shutdown_disposes_engine_when_factory_has_no_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """For a real ``async_sessionmaker`` (no ``close``), shutdown disposes the
        bound engine — releasing the connection pool rather than no-op'ing.
        """
        settings = _make_settings()
        engine = Mock()
        engine.dispose = AsyncMock()
        # Mimic async_sessionmaker: no `close`, engine reachable via `.kw['bind']`.
        factory = Mock(spec=["kw"])
        factory.kw = {"bind": engine}
        monkeypatch.setattr(
            worker_arq, "create_session_factory", Mock(return_value=factory)
        )

        async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
            await asyncio.Event().wait()

        on_startup, on_shutdown = build_worker_lifecycle(
            settings=settings,
            consumer_factory=consumer_factory,
            close_session_factory=True,
        )

        ctx: dict[str, Any] = {}
        await on_startup(ctx)
        await on_shutdown(ctx)

        engine.dispose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


def test_exported_from_core_shared() -> None:
    """The public symbols are re-exported from the top-level package."""
    import core_shared

    assert core_shared.SharedARQWorkerSettings is SharedARQWorkerSettings
    assert core_shared.generate_cron_jobs is generate_cron_jobs
    assert core_shared.build_worker_lifecycle is build_worker_lifecycle
    assert core_shared.default_retry_delay is default_retry_delay
    for name in (
        "SharedARQWorkerSettings",
        "generate_cron_jobs",
        "build_worker_lifecycle",
        "default_retry_delay",
    ):
        assert name in core_shared.__all__


def test_import_core_shared_without_arq() -> None:
    """``import core_shared`` (and ``worker_arq``) must work without ``arq``.

    ``arq`` pins ``redis<6`` against core_shared's ``redis>=8``, so it is a
    dev-only dependency and the toolkit imports it lazily. This runs in a
    subprocess with ``arq`` blocked at import time (the test process itself has
    ``arq`` installed), asserting the module-level imports never touch it and that
    ``generate_cron_jobs`` — the only ``arq``-dependent helper — fails only when
    actually called.
    """
    code = textwrap.dedent(
        """
        import builtins

        _real_import = builtins.__import__

        def _blocked(name, *args, **kwargs):
            if name == "arq" or name.startswith("arq."):
                raise ImportError("arq is blocked for this test")
            return _real_import(name, *args, **kwargs)

        builtins.__import__ = _blocked

        import core_shared
        import core_shared.worker_arq as wa

        assert hasattr(core_shared, "build_worker_lifecycle")
        # The lazy arq import surfaces only when the cron helper is invoked.
        try:
            wa.generate_cron_jobs(
                lambda ctx: None,
                enable_periodic_sync=True,
                sync_interval_hours=6,
            )
        except ImportError:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("generate_cron_jobs should require arq")

        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
