"""
Unit tests for the Strava ARQ worker.

Covers:
* ``process_strava_webhook_event`` task dispatch for create/update/delete
  aspect types and ignoring of non-activity events.
* ``StravaWorkerSettings`` after the ITER14-002 Phase 2 migration onto the
  shared ARQ toolkit — asserted through ``arq.worker.get_kwargs`` so we check
  what arq actually consumes (inherited ``SharedARQWorkerSettings`` defaults are
  *not* visible to arq, only leaf-class attributes are), plus delegation to the
  shared lifecycle factory and cron helper.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_mock_settings(**overrides: Any) -> MagicMock:
    """Build a mock ``StravaSettings`` with concrete (non-MagicMock) values.

    Concrete values matter: the migrated ``StravaWorkerSettings`` class body
    calls ``generate_cron_jobs(... sync_interval_hours=settings.sync_interval_hours)``
    and ``redis_settings_from_url(settings.redis_url)`` at import time, both of
    which require real values rather than auto-generated child mocks.
    """
    mock_settings = MagicMock()
    mock_settings.log_level = "DEBUG"
    mock_settings.worker_id = "strava-worker"
    mock_settings.redis_url = "redis://localhost:6379"
    mock_settings.stream_name = "pms:domain-events"
    mock_settings.queue_name = "arq:strava"
    mock_settings.enable_periodic_sync = False
    mock_settings.sync_interval_hours = 6
    mock_settings.database_url.get_secret_value.return_value = (
        "postgresql://test:test@localhost/test"
    )
    mock_settings.encryption_key.get_secret_value.return_value = (
        "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ9"  # noqa: S106
    )
    mock_settings.strava_client_id = "test_client"
    mock_settings.strava_client_secret.get_secret_value.return_value = "test_secret"  # noqa: S106
    for key, value in overrides.items():
        setattr(mock_settings, key, value)
    return mock_settings


def _import_worker(**setting_overrides: Any) -> Any:
    """Import the worker module with mocked settings.

    Re-imports a fresh ``worker`` module each call so the ``StravaWorkerSettings``
    class body is re-evaluated under the provided settings (needed to exercise the
    cron-enabled vs cron-disabled paths).
    """
    import importlib
    import sys

    mock_settings = _build_mock_settings(**setting_overrides)

    fake_strava_settings = MagicMock()
    fake_strava_settings.StravaSettings.return_value = mock_settings
    sys.modules["strava_settings"] = fake_strava_settings

    with (
        patch("core_shared.logging.configure_logging"),
        patch("core_shared.logging.get_logger", return_value=MagicMock()),
    ):
        if "worker" in sys.modules:
            del sys.modules["worker"]
        return importlib.import_module("worker")


def _make_session_factory_returning_none():
    """Create a session factory whose DB queries return no rows."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _session_ctx():
        yield mock_session

    return _session_ctx


class TestProcessStravaWebhookEvent:
    """Tests for the process_strava_webhook_event ARQ task function."""

    @pytest.fixture
    def ctx(self) -> dict[str, Any]:
        """ARQ worker context with mocked session factory."""
        return {
            "session_factory": _make_session_factory_returning_none(),
            "settings": MagicMock(
                encryption_key=MagicMock(
                    get_secret_value=MagicMock(return_value="test_key")
                ),
                strava_client_id="test",
                strava_client_secret=MagicMock(
                    get_secret_value=MagicMock(return_value="test_secret")
                ),
            ),
        }

    @pytest.mark.asyncio
    async def test_dispatches_create_event_skips_unknown_athlete(
        self, ctx: dict[str, Any]
    ) -> None:
        """Create event for unknown athlete is skipped gracefully."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "create",
            "object_type": "activity",
            "object_id": 12345,
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"
        assert result["reason"] == "unknown_athlete"

    @pytest.mark.asyncio
    async def test_dispatches_update_event_skips_unknown_athlete(
        self, ctx: dict[str, Any]
    ) -> None:
        """Update event for unknown athlete is skipped."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "update",
            "object_type": "activity",
            "object_id": 99999,
            "owner_id": 11111,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": {"title": "New Title"},
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_dispatches_delete_event_skips_unknown_athlete(
        self, ctx: dict[str, Any]
    ) -> None:
        """Delete event for unknown athlete is skipped."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "delete",
            "object_type": "activity",
            "object_id": 55555,
            "owner_id": 22222,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_ignores_non_activity_event(self, ctx: dict[str, Any]) -> None:
        """Non-activity (athlete) events are ignored."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "update",
            "object_type": "athlete",
            "object_id": 67890,
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "ignored"
        assert "athlete" in result["reason"]

    @pytest.mark.asyncio
    async def test_skips_missing_object_id(self, ctx: dict[str, Any]) -> None:
        """Event with missing object_id is skipped gracefully."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "create",
            "object_type": "activity",
            "object_id": None,
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"
        assert result["reason"] == "invalid_object_id"

    @pytest.mark.asyncio
    async def test_skips_non_int_object_id(self, ctx: dict[str, Any]) -> None:
        """Event with non-integer object_id is skipped gracefully."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "create",
            "object_type": "activity",
            "object_id": "not-an-int",
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"
        assert result["reason"] == "invalid_object_id"


class TestStravaWorkerSettings:
    """The migrated ``StravaWorkerSettings`` exposes the right arq config.

    Assertions go through ``arq.worker.get_kwargs`` because that is exactly what
    arq reads to build the ``Worker`` (only the leaf class ``__dict__`` plus arq's
    own constructor defaults — inherited ``SharedARQWorkerSettings`` attributes are
    not visible to arq). This is what guarantees behaviour is unchanged.
    """

    def test_functions_exposed(self) -> None:
        from arq.worker import get_kwargs

        worker_mod = _import_worker()
        # arq's get_kwargs has a buggy return annotation (dict[str, NameError]);
        # annotate explicitly so mypy sees the real values.
        kwargs: dict[str, Any] = get_kwargs(worker_mod.StravaWorkerSettings)

        names = {f.__name__ for f in kwargs["functions"]}
        assert names == {
            "process_strava_webhook_event",
            "sync_strava_activities",
            "sync_strava_activity_batch",
            "periodic_sync_all_strava_accounts",
            "reconcile_in_progress_parents",
        }

    def test_documented_overrides(self) -> None:
        from arq.worker import get_kwargs

        worker_mod = _import_worker()
        kwargs: dict[str, Any] = get_kwargs(worker_mod.StravaWorkerSettings)

        # Documented overrides retained on the leaf class.
        assert kwargs["max_tries"] == 20
        # max_jobs=5 deviates from arq's default of 10; kept for behaviour parity.
        assert kwargs["max_jobs"] == 5
        assert kwargs["queue_name"] == worker_mod.STRAVA_ARQ_QUEUE_NAME

    def test_lifecycle_hooks_and_redis_settings_present(self) -> None:
        from arq.worker import get_kwargs

        worker_mod = _import_worker()
        kwargs: dict[str, Any] = get_kwargs(worker_mod.StravaWorkerSettings)

        assert callable(kwargs["on_startup"])
        assert callable(kwargs["on_shutdown"])
        assert kwargs["redis_settings"] is not None

    def test_inherited_defaults_are_what_arq_consumes(self) -> None:
        """The values arq actually builds the Worker from (via get_kwargs +
        arq's own constructor defaults) match the pre-migration behaviour.

        Because get_kwargs reads only the leaf __dict__, the inherited shared
        defaults are absent from get_kwargs and arq falls back to its own
        defaults — which equal the shared ones for job_timeout/keep_result, and
        is 3600 (not the shared 30) for health_check_interval, exactly as before
        the migration since strava never declared it.
        """
        from arq.worker import Worker, get_kwargs

        worker_mod = _import_worker()
        kwargs: dict[str, Any] = get_kwargs(worker_mod.StravaWorkerSettings)
        worker = Worker(**kwargs, redis_pool=MagicMock())
        # job_timeout/keep_result: shared defaults == arq defaults (300/3600).
        assert worker.job_timeout_s == 300
        assert worker.keep_result_s == 3600
        # health_check_interval stays at arq's 3600 (the shared 30 is not visible
        # to arq via inheritance, and strava never declared it).
        assert worker.health_check_interval == 3600

    def test_no_redundant_defaults_redeclared_on_leaf(self) -> None:
        """job_timeout/keep_result match arq defaults, so they must not be
        redeclared on the leaf (they come from the shared toolkit intent)."""
        worker_mod = _import_worker()
        leaf = worker_mod.StravaWorkerSettings.__dict__
        assert "job_timeout" not in leaf
        assert "keep_result" not in leaf
        # The deleted local retry helper and consumer callback are gone.
        assert not hasattr(worker_mod, "retry_delay_func")
        assert not hasattr(worker_mod, "_on_consumer_task_done")
        assert not hasattr(worker_mod, "startup")
        assert not hasattr(worker_mod, "shutdown")


class TestStravaCronScheduling:
    """Cron jobs are the shared ``generate_cron_jobs`` periodic-sync cron plus the
    always-on fan-out reconciliation cron (ITER14-003 Phase 4)."""

    @staticmethod
    def _reconciliation_crons(cron_jobs: list[Any]) -> list[Any]:
        """The reconciliation cron fires every 5 minutes ({0,5,…,55})."""
        return [
            c
            for c in cron_jobs
            if isinstance(getattr(c, "minute", None), set) and len(c.minute) == 12
        ]

    def test_reconciliation_cron_present_when_periodic_sync_disabled(self) -> None:
        worker_mod = _import_worker(enable_periodic_sync=False)
        cron_jobs = worker_mod.StravaWorkerSettings.cron_jobs
        # Periodic sync off, but reconciliation still runs.
        assert len(cron_jobs) == 1
        assert len(self._reconciliation_crons(cron_jobs)) == 1

    def test_reconciliation_cron_present_with_periodic_sync(self) -> None:
        worker_mod = _import_worker(enable_periodic_sync=True, sync_interval_hours=6)
        cron_jobs = worker_mod.StravaWorkerSettings.cron_jobs
        # Periodic-sync cron + reconciliation cron.
        assert len(cron_jobs) == 2
        assert len(self._reconciliation_crons(cron_jobs)) == 1
        # The periodic-sync cron keeps firing at the configured interval hours.
        periodic = [c for c in cron_jobs if getattr(c, "hour", None) == {0, 6, 12, 18}]
        assert len(periodic) == 1

    def test_reconciliation_cron_targets_reconcile_function(self) -> None:
        worker_mod = _import_worker(enable_periodic_sync=False)
        recon = self._reconciliation_crons(worker_mod.StravaWorkerSettings.cron_jobs)[0]
        assert recon.coroutine.__name__ == "reconcile_in_progress_parents"


class TestStravaLifecycleDelegation:
    """Startup/shutdown delegate to the shared ``build_worker_lifecycle`` factory."""

    def test_delegates_to_shared_factory_with_strava_options(self) -> None:
        import sys

        # Patch the shared factory before the worker imports it so the
        # `from core_shared import build_worker_lifecycle` binding picks up the mock.
        startup, shutdown = MagicMock(name="on_startup"), MagicMock(name="on_shutdown")
        with patch(
            "core_shared.build_worker_lifecycle",
            return_value=(startup, shutdown),
        ) as mock_factory:
            if "worker" in sys.modules:
                del sys.modules["worker"]
            worker_mod = _import_worker()

        mock_factory.assert_called_once()
        call = mock_factory.call_args
        # Strava logs consumer errors in real time and does NOT close the
        # session factory on shutdown.
        assert call.kwargs["log_consumer_errors"] is True
        assert call.kwargs["close_session_factory"] is False
        assert callable(call.kwargs["consumer_factory"])
        # The built hooks are wired onto the settings class.
        assert worker_mod.StravaWorkerSettings.on_startup is startup
        assert worker_mod.StravaWorkerSettings.on_shutdown is shutdown

    @pytest.mark.asyncio
    async def test_consumer_factory_runs_strava_stream_consumer(self) -> None:
        """The consumer factory wires redis_url/stream_name from settings into
        run_strava_stream_consumer."""
        captured: dict[str, Any] = {}

        def _capture(*_a: Any, **kwargs: Any) -> tuple[Any, Any]:
            captured.update(kwargs)
            return (MagicMock(), MagicMock())

        with patch("core_shared.build_worker_lifecycle", side_effect=_capture):
            _import_worker()

        consumer_factory = captured["consumer_factory"]
        fake_settings = MagicMock(
            redis_url="redis://example:6379", stream_name="pms:domain-events"
        )
        with patch(
            "stream_consumer_tasks.run_strava_stream_consumer",
            new=AsyncMock(),
        ) as mock_run:
            await consumer_factory(MagicMock(name="session_factory"), fake_settings)

        mock_run.assert_awaited_once()
        assert mock_run.await_args is not None
        assert mock_run.await_args.kwargs["redis_url"] == "redis://example:6379"
        assert mock_run.await_args.kwargs["stream_name"] == "pms:domain-events"
