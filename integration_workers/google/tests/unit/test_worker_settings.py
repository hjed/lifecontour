"""Unit tests for ``GoogleWorkerSettings`` after the ITER14-002 Phase 2 migration.

The Google worker now builds its ARQ ``WorkerSettings`` from the shared
``core_shared`` toolkit (``SharedARQWorkerSettings`` defaults, the
``build_worker_lifecycle`` factory, the ``generate_cron_jobs`` helper, and
``redis_settings_from_url``). These tests assert the migrated settings through
``arq.worker.get_kwargs`` — what arq actually consumes (only the leaf class
``__dict__`` plus arq's own constructor defaults; inherited shared defaults are
*not* visible to arq) — and verify lifecycle delegation, guaranteeing behaviour
is unchanged.

Cron scheduling parity is covered by ``test_periodic_sync.py``.
"""

from __future__ import annotations

import importlib
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BASE_ENV = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-secret",
    "ENCRYPTION_KEY": "test-encryption-key",
}


def _reload_worker(**env: str) -> Any:
    """Reload the worker module under a given environment.

    Reloading re-evaluates the ``GoogleWorkerSettings`` class body (and the
    module-level lifecycle wiring) so settings reflect the patched environment.
    """
    import worker

    with patch.dict(os.environ, {**_BASE_ENV, **env}):
        importlib.reload(worker)
    return worker


class TestGoogleWorkerSettings:
    """``GoogleWorkerSettings`` exposes the expected arq configuration."""

    def test_functions_exposed(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.GoogleWorkerSettings)

        names = {f.__name__ for f in kwargs["functions"]}
        assert names == {
            "sync_google_contacts",
            "push_local_contacts_to_google",
            "sync_calendar_events",
            "setup_calendar_webhook",
            "renew_calendar_webhooks",
            "periodic_sync_all_accounts",
        }

    def test_webhook_renewal_cron_is_independent_of_periodic_sync(self) -> None:
        """Push channels lapse whether or not periodic sync is enabled.

        Gating renewal on ``enable_periodic_sync`` would disable it precisely
        where push notifications are the only thing keeping calendars fresh, so
        the renewal cron is registered either way.
        """
        from arq.worker import get_kwargs

        worker = _reload_worker(ENABLE_PERIODIC_SYNC="false")
        kwargs: dict[str, Any] = get_kwargs(worker.GoogleWorkerSettings)

        cron_names = {job.coroutine.__name__ for job in kwargs["cron_jobs"]}
        assert "periodic_sync_all_accounts" not in cron_names
        assert "renew_calendar_webhooks" in cron_names

    def test_webhook_renewal_cron_present_with_periodic_sync(self) -> None:
        """Both crons are registered when periodic sync is enabled."""
        from arq.worker import get_kwargs

        worker = _reload_worker(ENABLE_PERIODIC_SYNC="true", SYNC_INTERVAL_HOURS="6")
        kwargs: dict[str, Any] = get_kwargs(worker.GoogleWorkerSettings)

        cron_names = {job.coroutine.__name__ for job in kwargs["cron_jobs"]}
        assert cron_names == {
            "periodic_sync_all_accounts",
            "renew_calendar_webhooks",
        }

    def test_documented_overrides(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.GoogleWorkerSettings)

        # job_timeout=600 (10 min) is google's documented override.
        assert kwargs["job_timeout"] == 600
        # max_jobs follows the worker's max_concurrent_jobs setting.
        assert kwargs["max_jobs"] == worker.settings.max_concurrent_jobs
        assert kwargs["queue_name"] == worker.ARQ_QUEUE_NAME

    def test_lifecycle_hooks_and_redis_settings_present(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.GoogleWorkerSettings)

        assert callable(kwargs["on_startup"])
        assert callable(kwargs["on_shutdown"])
        assert kwargs["redis_settings"] is not None

    def test_inherited_defaults_are_what_arq_consumes(self) -> None:
        """The values arq actually builds the Worker from match pre-migration
        behaviour: keep_result/max_tries fall back to arq's own defaults (which
        equal the shared defaults), and health_check_interval stays at arq's
        3600 (the shared 30 is invisible to arq via inheritance, and google never
        declared it)."""
        from arq.worker import Worker, get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.GoogleWorkerSettings)
        arq_worker = Worker(**kwargs, redis_pool=MagicMock())

        assert arq_worker.keep_result_s == 3600
        assert arq_worker.max_tries == 5
        assert arq_worker.health_check_interval == 3600
        # job_timeout is google's leaf override (10 min).
        assert arq_worker.job_timeout_s == 600

    def test_no_redundant_defaults_or_deleted_helpers(self) -> None:
        """keep_result/max_tries match arq defaults, so they are not redeclared
        on the leaf; the local retry helper and lifecycle functions are gone."""
        worker = _reload_worker()
        leaf = worker.GoogleWorkerSettings.__dict__
        assert "keep_result" not in leaf
        assert "max_tries" not in leaf
        assert "retry_delay" not in leaf
        assert not hasattr(worker, "retry_delay_func")
        assert not hasattr(worker, "startup")
        assert not hasattr(worker, "shutdown")


class TestGoogleLifecycleDelegation:
    """Startup/shutdown delegate to the shared ``build_worker_lifecycle`` factory."""

    def test_delegates_to_shared_factory_with_google_options(self) -> None:
        startup, shutdown = MagicMock(name="on_startup"), MagicMock(name="on_shutdown")
        with patch(
            "core_shared.build_worker_lifecycle",
            return_value=(startup, shutdown),
        ) as mock_factory:
            worker = _reload_worker()

        mock_factory.assert_called_once()
        call = mock_factory.call_args
        # Google closes the session factory on shutdown and does NOT attach the
        # real-time consumer-error done-callback.
        assert call.kwargs["close_session_factory"] is True
        assert call.kwargs["log_consumer_errors"] is False
        assert callable(call.kwargs["consumer_factory"])
        assert worker.GoogleWorkerSettings.on_startup is startup
        assert worker.GoogleWorkerSettings.on_shutdown is shutdown

    @pytest.mark.asyncio
    async def test_consumer_factory_runs_google_stream_consumer(self) -> None:
        """The consumer factory wires redis_url/stream_name from settings into
        run_google_stream_consumer."""
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
            "stream_consumer_tasks.run_google_stream_consumer",
            new=AsyncMock(),
        ) as mock_run:
            await consumer_factory(MagicMock(name="session_factory"), fake_settings)

        mock_run.assert_awaited_once()
        assert mock_run.await_args is not None
        assert mock_run.await_args.kwargs["redis_url"] == "redis://example:6379"
        assert mock_run.await_args.kwargs["stream_name"] == "pms:domain-events"
