# ruff: noqa: E402
import os
from unittest.mock import AsyncMock, MagicMock, patch

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

import pytest
from arq.connections import RedisSettings

from worker import (
    _parse_redis_url,
    sync_snipeit_asset_batch,
    sync_snipeit_assets,
    sync_snipeit_maintenance_batch,
    sync_snipeit_maintenances,
)


def test_parse_redis_url() -> None:
    """Test parsing a redis URL into ARQ RedisSettings."""
    settings: RedisSettings = _parse_redis_url("redis://localhost:6379/1")
    assert settings.host == "localhost"
    assert settings.port == 6379
    assert settings.database == 1
    assert settings.password is None


def test_parse_redis_url_with_password() -> None:
    """Test parsing a redis URL with a password."""
    settings: RedisSettings = _parse_redis_url("redis://:mypassword@redis-host:6380/2")
    assert settings.host == "redis-host"
    assert settings.port == 6380
    assert settings.database == 2
    assert settings.password == "mypassword"


class MockRedis:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, function, *args, **kwargs):
        self.jobs.append((function, args, kwargs))


@pytest.fixture
def mock_ctx():
    return {
        "redis": MockRedis(),
        "session_factory": MagicMock(),
    }


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
