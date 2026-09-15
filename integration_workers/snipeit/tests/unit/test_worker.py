# ruff: noqa: E402
"""Unit tests for the Snipe-IT worker after the ITER14-002 Phase 3 migration onto
the shared ``core_shared`` ARQ toolkit.

The worker now builds its ARQ ``WorkerSettings`` from ``SharedARQWorkerSettings``
defaults, the ``build_worker_lifecycle`` factory, and ``redis_settings_from_url``.
Snipe-IT has no periodic sync, so it declares no cron jobs. These tests assert the
migrated settings through ``arq.worker.get_kwargs`` (what arq actually consumes:
only the leaf class ``__dict__`` plus arq's own defaults) and verify lifecycle
delegation, alongside the task-orchestration tests.
"""

import importlib
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

import pytest
from core_shared.testing import make_arq_ctx

from worker import (
    sync_snipeit_asset_batch,
    sync_snipeit_assets,
    sync_snipeit_maintenance_batch,
    sync_snipeit_maintenances,
)

_BASE_ENV = {
    "DATABASE_URL": os.environ["DATABASE_URL"],
    "ENCRYPTION_KEY": "testkey",
}

# Worker-managed env vars (BaseWorkerSettings surface + Snipe-IT-specific). Cleared
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


class TestSnipeItWorkerSettings:
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
            "sync_snipeit_assets",
            "sync_snipeit_asset_batch",
            "sync_snipeit_maintenances",
            "sync_snipeit_maintenance_batch",
            "periodic_checkin_all_snipeit_accounts",
        }

    def test_queue_name(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.WorkerSettings)
        assert kwargs["queue_name"] == "arq:snipeit"

    def test_lifecycle_hooks_and_redis_settings_present(self) -> None:
        from arq.worker import get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.WorkerSettings)

        assert callable(kwargs["on_startup"])
        assert callable(kwargs["on_shutdown"])
        assert kwargs["redis_settings"] is not None

    def test_health_check_interval_preserved(self) -> None:
        """``health_check_interval=30`` is snipeit's documented override, declared on
        the leaf so arq keeps the pre-migration 30s ping (the inherited shared 30 is
        invisible to arq)."""
        from arq.worker import Worker, get_kwargs

        worker = _reload_worker()
        kwargs: dict[str, Any] = get_kwargs(worker.WorkerSettings)
        arq_worker = Worker(**kwargs, redis_pool=MagicMock())

        assert arq_worker.health_check_interval == 30
        assert arq_worker.keep_result_s == 3600
        assert arq_worker.max_tries == 5
        assert arq_worker.job_timeout_s == 300

    def test_schedules_checkin_sweep_when_periodic_sync_enabled(self) -> None:
        """When periodic sync is enabled, the worker schedules the check-in sweep."""
        worker = _reload_worker(ENABLE_PERIODIC_SYNC="true", SYNC_INTERVAL_HOURS="6")
        cron_jobs = worker.WorkerSettings.cron_jobs
        assert len(cron_jobs) == 1
        assert (
            cron_jobs[0].coroutine.__name__ == "periodic_checkin_all_snipeit_accounts"
        )
        assert cron_jobs[0].hour == {0, 6, 12, 18}

    def test_schedules_nothing_when_periodic_sync_disabled(self) -> None:
        """With periodic sync disabled (the default), no cron jobs are scheduled."""
        worker = _reload_worker(ENABLE_PERIODIC_SYNC="false")
        assert not worker.WorkerSettings.cron_jobs

    def test_no_residual_local_helpers(self) -> None:
        """The duplicated Redis helper and per-worker lifecycle functions are gone."""
        worker = _reload_worker()
        assert not hasattr(worker, "_parse_redis_url")
        assert not hasattr(worker, "startup")
        assert not hasattr(worker, "shutdown")


class TestSnipeItLifecycleDelegation:
    """Startup/shutdown delegate to the shared ``build_worker_lifecycle`` factory."""

    def test_delegates_to_shared_factory_with_snipeit_options(self) -> None:
        startup, shutdown = MagicMock(name="on_startup"), MagicMock(name="on_shutdown")
        with patch(
            "core_shared.build_worker_lifecycle",
            return_value=(startup, shutdown),
        ) as mock_factory:
            worker = _reload_worker()

        mock_factory.assert_called_once()
        call = mock_factory.call_args
        assert call.kwargs["close_session_factory"] is False
        assert call.kwargs["log_consumer_errors"] is True
        assert callable(call.kwargs["consumer_factory"])
        assert worker.WorkerSettings.on_startup is startup
        assert worker.WorkerSettings.on_shutdown is shutdown

    @pytest.mark.asyncio
    async def test_consumer_factory_runs_snipeit_stream_consumer(self) -> None:
        """The consumer factory wires redis_url/stream_name from settings into
        run_snipeit_stream_consumer."""
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
            "stream_consumer_tasks.run_snipeit_stream_consumer",
            new=AsyncMock(),
        ) as mock_run:
            await consumer_factory(MagicMock(name="session_factory"), fake_settings)

        mock_run.assert_awaited_once()
        assert mock_run.await_args is not None
        assert mock_run.await_args.kwargs["redis_url"] == "redis://example:6379"
        assert mock_run.await_args.kwargs["stream_name"] == "pms:domain-events"


class MockRedis:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, function, *args, **kwargs):
        self.jobs.append((function, args, kwargs))


@pytest.fixture
def mock_ctx():
    # Custom MockRedis (records enqueued jobs) and a bare MagicMock session
    # factory configured per-test, layered onto the shared ARQ ctx scaffolding.
    return make_arq_ctx(redis=MockRedis(), session_factory=MagicMock())


@pytest.mark.asyncio
async def test_sync_snipeit_assets_orchestrator(mock_ctx):
    """Test the orchestrator job enqueues batch jobs."""
    user_id = "user-123"

    with (
        patch("worker._get_auth_data", new_callable=AsyncMock) as mock_auth_data,
        patch("worker._create_sync_service") as mock_create_service,
    ):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = type(
            "Row", (), {"base_url": "https://snipeit.com", "snipeit_user_id": "1"}
        )()

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_ctx["session_factory"].return_value.__aenter__.return_value = mock_session

        mock_auth_data.return_value = {
            "encrypted_api_key": b"api-key",
        }

        mock_sync_service = MagicMock()

        async def mock_batches():
            yield [1, 2, 3]
            yield [4, 5]

        mock_sync_service.list_asset_batches.return_value = mock_batches()
        mock_sync_service._api_client.close = AsyncMock()
        mock_create_service.return_value = mock_sync_service

        await sync_snipeit_assets(mock_ctx, user_id)

        assert len(mock_ctx["redis"].jobs) == 2

        job1 = mock_ctx["redis"].jobs[0]
        assert job1[0] == "sync_snipeit_asset_batch"
        assert job1[1] == (user_id, [1, 2, 3])

        job2 = mock_ctx["redis"].jobs[1]
        assert job2[0] == "sync_snipeit_asset_batch"
        assert job2[1] == (user_id, [4, 5])


@pytest.mark.asyncio
async def test_sync_snipeit_assets_ignores_otel_carrier(mock_ctx):
    """Test that the orchestrator job accepts and strips otel_carrier kwargs."""
    user_id = "user-123"

    with (
        patch("worker._get_auth_data", new_callable=AsyncMock) as mock_auth_data,
        patch("worker._create_sync_service") as mock_create_service,
    ):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = type(
            "Row", (), {"base_url": "https://snipeit.com", "snipeit_user_id": "1"}
        )()

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_ctx["session_factory"].return_value.__aenter__.return_value = mock_session
        mock_auth_data.return_value = {"encrypted_api_key": b"api-key"}

        mock_sync_service = MagicMock()

        async def mock_batches():
            yield []

        mock_sync_service.list_asset_batches.return_value = mock_batches()
        mock_sync_service._api_client.close = AsyncMock()
        mock_create_service.return_value = mock_sync_service

        # This should not raise TypeError: sync_snipeit_assets() got an unexpected keyword argument 'otel_carrier'
        await sync_snipeit_assets(
            mock_ctx, user_id, otel_carrier={"traceparent": "00-1234-5678-01"}
        )

        # Verify it completed successfully without error
        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_sync_snipeit_asset_batch(mock_ctx):
    """Test the batch worker job."""
    user_id = "user-123"
    asset_ids = [1, 2, 3]

    with (
        patch("worker._get_auth_data", new_callable=AsyncMock) as mock_auth_data,
        patch("worker._create_sync_service") as mock_create_service,
    ):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = type(
            "Row", (), {"base_url": "https://snipeit.com", "snipeit_user_id": "1"}
        )()

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_ctx["session_factory"].return_value.__aenter__.return_value = mock_session

        mock_auth_data.return_value = {
            "encrypted_api_key": b"api-key",
        }

        mock_sync_service = MagicMock()
        mock_sync_service.sync_asset_batch = AsyncMock(
            return_value={"synced": 3, "skipped": 0, "failed": 0}
        )
        mock_sync_service._api_client.close = AsyncMock()
        mock_create_service.return_value = mock_sync_service

        result = await sync_snipeit_asset_batch(mock_ctx, user_id, asset_ids)

        assert result == {"synced": 3, "skipped": 0, "failed": 0}
        mock_sync_service.sync_asset_batch.assert_called_once_with(
            asset_ids=asset_ids, session_factory=mock_ctx["session_factory"]
        )


@pytest.mark.asyncio
async def test_sync_snipeit_maintenances_orchestrator(mock_ctx):
    """Test the maintenance orchestrator job enqueues batch jobs."""
    user_id = "user-123"

    with (
        patch("worker._get_auth_data", new_callable=AsyncMock) as mock_auth_data,
        patch("worker._create_sync_service") as mock_create_service,
    ):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = type(
            "Row", (), {"base_url": "https://snipeit.com", "snipeit_user_id": "1"}
        )()

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_ctx["session_factory"].return_value.__aenter__.return_value = mock_session

        mock_auth_data.return_value = {
            "encrypted_api_key": b"api-key",
        }

        mock_sync_service = MagicMock()

        async def mock_batches():
            yield [10, 20]
            yield [30]

        mock_sync_service.list_maintenance_batches.return_value = mock_batches()
        mock_sync_service._api_client.close = AsyncMock()
        mock_create_service.return_value = mock_sync_service

        await sync_snipeit_maintenances(mock_ctx, user_id)

        assert len(mock_ctx["redis"].jobs) == 2

        job1 = mock_ctx["redis"].jobs[0]
        assert job1[0] == "sync_snipeit_maintenance_batch"
        assert job1[1] == (user_id, [10, 20])

        job2 = mock_ctx["redis"].jobs[1]
        assert job2[0] == "sync_snipeit_maintenance_batch"
        assert job2[1] == (user_id, [30])


@pytest.mark.asyncio
async def test_sync_snipeit_maintenances_accepts_sync_type_and_otel_carrier(mock_ctx):
    """Test that the maintenance orchestrator accepts sync_type and otel_carrier.

    enqueue_snipeit_maintenance_sync passes sync_type as a positional arg
    and otel_carrier as a keyword arg. This test verifies the worker function
    signature is compatible with that calling convention.
    """
    user_id = "user-123"

    with (
        patch("worker._get_auth_data", new_callable=AsyncMock) as mock_auth_data,
        patch("worker._create_sync_service") as mock_create_service,
    ):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = type(
            "Row", (), {"base_url": "https://snipeit.com", "snipeit_user_id": "1"}
        )()

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_ctx["session_factory"].return_value.__aenter__.return_value = mock_session
        mock_auth_data.return_value = {"encrypted_api_key": b"api-key"}

        mock_sync_service = MagicMock()

        async def mock_batches():
            yield []

        mock_sync_service.list_maintenance_batches.return_value = mock_batches()
        mock_sync_service._api_client.close = AsyncMock()
        mock_create_service.return_value = mock_sync_service

        # Call with sync_type positional and otel_carrier keyword - matches enqueue call
        await sync_snipeit_maintenances(
            mock_ctx, user_id, "full", otel_carrier={"traceparent": "00-1234-5678-01"}
        )

        mock_sync_service._api_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_sync_snipeit_maintenance_batch(mock_ctx):
    """Test the maintenance batch worker job."""
    user_id = "user-123"
    maintenance_ids = [10, 20, 30]

    with (
        patch("worker._get_auth_data", new_callable=AsyncMock) as mock_auth_data,
        patch("worker._create_sync_service") as mock_create_service,
    ):
        mock_result = MagicMock()
        mock_result.fetchone.return_value = type(
            "Row", (), {"base_url": "https://snipeit.com", "snipeit_user_id": "1"}
        )()

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_ctx["session_factory"].return_value.__aenter__.return_value = mock_session

        mock_auth_data.return_value = {
            "encrypted_api_key": b"api-key",
        }

        mock_sync_service = MagicMock()
        mock_sync_service.sync_maintenance_batch = AsyncMock(
            return_value={"synced": 2, "skipped": 1, "failed": 0}
        )
        mock_sync_service._api_client.close = AsyncMock()
        mock_create_service.return_value = mock_sync_service

        result = await sync_snipeit_maintenance_batch(
            mock_ctx, user_id, maintenance_ids
        )

        assert result == {"synced": 2, "skipped": 1, "failed": 0}
        mock_sync_service.sync_maintenance_batch.assert_called_once_with(
            maintenance_ids=maintenance_ids,
            session_factory=mock_ctx["session_factory"],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("did_checkin", "reconciles"),
    [(True, 1), (False, 0)],
    ids=["checked-in", "nothing-to-check-in"],
)
async def test_periodic_checkin_reconciles_after_a_checkin(
    mock_ctx: dict[str, Any], did_checkin: bool, reconciles: int
) -> None:
    """A sweep check-in may close a checkout recorded on an outdated date.

    Reconciling straight after lets that journal's corrected pair be recorded;
    nothing else would revisit it once the asset is back.
    """
    from datetime import date, datetime

    from snipeit_sync_service import AssetUsageDates, OverdueGearUsage
    from worker import periodic_checkin_all_snipeit_accounts

    settings_result = MagicMock()
    settings_result.fetchall.return_value = [
        MagicMock(
            user_id="user-1",
            base_url="https://snipeit.example.com",
            snipeit_user_id="5",
        )
    ]
    mock_session = AsyncMock()
    mock_session.execute.return_value = settings_result
    mock_ctx["session_factory"].return_value.__aenter__.return_value = mock_session

    mock_sync_service = MagicMock()
    mock_sync_service.push_checkin_create = AsyncMock(return_value=did_checkin)
    mock_sync_service.reconcile_gear_usage = AsyncMock()
    mock_sync_service._api_client.close = AsyncMock()
    overdue = OverdueGearUsage(
        journal_id=100,
        checkout_at=date(2025, 3, 8),
        checkin_at=date(2025, 3, 9),
        usage_dates=AssetUsageDates(last_checkin=datetime(2025, 3, 9, 17, 0)),
    )

    with (
        patch(
            "worker._get_auth_data",
            new_callable=AsyncMock,
            return_value={"encrypted_api_key": b"api-key"},
        ),
        patch("worker._create_sync_service", return_value=mock_sync_service),
        patch(
            "snipeit_sync_service.fetch_overdue_gear_usage",
            new_callable=AsyncMock,
            return_value=[overdue],
        ),
    ):
        await periodic_checkin_all_snipeit_accounts(mock_ctx)

    assert mock_sync_service.reconcile_gear_usage.await_count == reconciles
    checkin_kwargs = mock_sync_service.push_checkin_create.await_args.kwargs
    assert checkin_kwargs["usage_dates"] is overdue.usage_dates
