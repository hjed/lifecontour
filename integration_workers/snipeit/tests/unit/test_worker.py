import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq.connections import RedisSettings

from worker import _parse_redis_url, sync_snipeit_asset_batch, sync_snipeit_assets

db_port = os.environ.get("WORKSPACE_PORT_POSTGRES", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"


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
            "encrypted_access_token": b"access",
            "encrypted_refresh_token": b"refresh",
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
            "encrypted_access_token": b"access",
            "encrypted_refresh_token": b"refresh",
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
