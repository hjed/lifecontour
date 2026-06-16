# ruff: noqa: E402
"""Unit tests for the Immich worker ARQ configuration after the ITER14-002 Phase 3
migration onto the shared ``core_shared`` ARQ toolkit.

The worker now builds its ARQ ``WorkerSettings`` from ``SharedARQWorkerSettings``
defaults, the ``build_worker_lifecycle`` factory, the ``generate_cron_jobs`` helper,
and ``redis_settings_from_url``. These tests assert the migrated settings through
``arq.worker.get_kwargs`` — what arq actually consumes (only the leaf class
``__dict__`` plus arq's own constructor defaults; inherited shared defaults are
*not* visible to arq) — and verify lifecycle delegation, guaranteeing behaviour is
unchanged.
"""

from __future__ import annotations

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}"
        "/personal_management_test"
    )
os.environ.setdefault("ENCRYPTION_KEY", "testkey")

import importlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BASE_ENV = {
    "DATABASE_URL": os.environ["DATABASE_URL"],
    "ENCRYPTION_KEY": "testkey",
}

# Worker-managed env vars (BaseWorkerSettings surface + Immich-specific). Cleared
# before each reload so ambient values cannot leak into the reloaded settings.
_MANAGED_ENV = (
    "DATABASE_URL",
    "REDIS_URL",
    "STREAM_NAME",
    "WORKER_ID",
    "QUEUE_NAME",
    "LOG_LEVEL",
    "ENABLE_PERIODIC_SYNC",
    "SYNC_INTERVAL_HOURS",
    "ENABLE_TELEMETRY",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
    "OTEL_RESOURCE_ATTRIBUTES",
    "ENCRYPTION_KEY",
)


def _reload_worker(**env: str) -> Any:
    """Reload the worker module under a clean, explicit environment.

    Clears all worker-managed env vars first so ambient values (e.g.
    ``ENABLE_PERIODIC_SYNC``, ``REDIS_URL``) cannot leak into the reload and make
    these tests non-deterministic; only ``_BASE_ENV`` plus the explicit overrides
    apply. Reloading re-evaluates the ``WorkerSettings`` class body and the
    module-level lifecycle wiring so settings reflect that environment.
    """
    import worker

    effective = {**_BASE_ENV, **env}
    with patch.dict(os.environ, effective, clear=False):
        for name in _MANAGED_ENV:
            if name not in effective:
                os.environ.pop(name, None)
        importlib.reload(worker)
    return worker


class TestImmichWorkerSettings:
    """``WorkerSettings`` exposes the expected arq configuration."""

    def test_subclasses_shared_toolkit(self) -> None:
        from core_shared import SharedARQWorkerSettings

        worker = _reload_worker()
        assert issubclass(worker.WorkerSettings, SharedARQWorkerSettings)

    def test_functions_exposed(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.WorkerSettings)

        names = {f.__name__ for f in kwargs["functions"]}
        assert names == {
            "sync_immich_people",
            "sync_immich_people_batch",
            "sync_immich_albums",
            "sync_immich_album_batch",
            "periodic_sync_all_immich_accounts",
            "process_contact_event",
        }

    def test_queue_name(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.WorkerSettings)
        assert kwargs["queue_name"] == "arq:immich"

    def test_lifecycle_hooks_and_redis_settings_present(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.WorkerSettings)

        assert callable(kwargs["on_startup"])
        assert callable(kwargs["on_shutdown"])
        assert kwargs["redis_settings"] is not None

    def test_health_check_interval_preserved(self) -> None:
        """``health_check_interval`` stays declared on the leaf at 30 so arq keeps
        the pre-migration 30s ping (the inherited shared 30 is invisible to arq)."""
        from arq.worker import Worker, get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.WorkerSettings)
        arq_worker = Worker(**kwargs, redis_pool=MagicMock())

        assert arq_worker.health_check_interval == 30
        # Operational defaults that equal arq's own defaults are inherited from the
        # shared base, not redeclared on the leaf.
        assert arq_worker.keep_result_s == 3600
        assert arq_worker.max_tries == 5
        assert arq_worker.job_timeout_s == 300

    def test_no_residual_local_helpers(self) -> None:
        """The duplicated Redis/cron helpers and per-worker lifecycle functions are
        gone after the migration."""
        worker = _reload_worker()
        assert not hasattr(worker, "_parse_redis_url")
        assert not hasattr(worker, "_generate_cron_jobs")
        assert not hasattr(worker, "startup")
        assert not hasattr(worker, "shutdown")


class TestImmichCronScheduling:
    """Cron jobs are produced by the shared ``generate_cron_jobs`` helper."""

    def test_cron_scheduled_when_periodic_sync_enabled(self) -> None:
        worker = _reload_worker(ENABLE_PERIODIC_SYNC="true", SYNC_INTERVAL_HOURS="6")
        assert len(worker.WorkerSettings.cron_jobs) == 1

    def test_no_cron_when_periodic_sync_disabled(self) -> None:
        worker = _reload_worker(ENABLE_PERIODIC_SYNC="false")
        assert worker.WorkerSettings.cron_jobs == []


class TestImmichLifecycleDelegation:
    """Startup/shutdown delegate to the shared ``build_worker_lifecycle`` factory."""

    def test_delegates_to_shared_factory_with_immich_options(self) -> None:
        startup, shutdown = MagicMock(name="on_startup"), MagicMock(name="on_shutdown")
        with patch(
            "core_shared.build_worker_lifecycle",
            return_value=(startup, shutdown),
        ) as mock_factory:
            worker = _reload_worker()

        mock_factory.assert_called_once()
        call = mock_factory.call_args
        # Immich preserves its pre-migration shutdown: it does not dispose the
        # session factory and logs consumer errors in real time.
        assert call.kwargs["close_session_factory"] is False
        assert call.kwargs["log_consumer_errors"] is True
        assert callable(call.kwargs["consumer_factory"])
        assert worker.WorkerSettings.on_startup is startup
        assert worker.WorkerSettings.on_shutdown is shutdown

    @pytest.mark.asyncio
    async def test_consumer_factory_runs_immich_stream_consumer(self) -> None:
        """The consumer factory wires redis_url/stream_name from settings into
        run_immich_stream_consumer."""
        captured: dict[str, Any] = {}

        def _capture(*_a: Any, **kwargs: Any) -> tuple[Any, Any]:
            captured.update(kwargs)
            return (MagicMock(), MagicMock())

        with patch("core_shared.build_worker_lifecycle", side_effect=_capture):
            _reload_worker()

        consumer_factory = captured["consumer_factory"]
        fake_settings = MagicMock(
            redis_url="redis://example:6379", stream_name="pms:domain-events"
        )
        with patch(
            "stream_consumer_tasks.run_immich_stream_consumer",
            new=AsyncMock(),
        ) as mock_run:
            await consumer_factory(MagicMock(name="session_factory"), fake_settings)

        mock_run.assert_awaited_once()
        assert mock_run.await_args is not None
        assert mock_run.await_args.kwargs["redis_url"] == "redis://example:6379"
        assert mock_run.await_args.kwargs["stream_name"] == "pms:domain-events"
