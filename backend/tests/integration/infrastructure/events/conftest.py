import os
import uuid

import pytest
import pytest_asyncio
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis


def _get_redis_test_url() -> str:
    """Get Redis URL for integration tests."""
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        return os.getenv("REDIS_URL", "redis://localhost:6379")

    from tests.integration.conftest import workspace_env

    port = workspace_env.get("REDIS_TEST_PORT", "6380")
    return f"redis://localhost:{port}"


@pytest.fixture
def test_stream_name() -> str:
    """Provide a unique stream name for each test."""
    return f"pms:test-events-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def redis_client(test_stream_name: str):
    """Create a real Redis client for testing and clean up the stream afterward."""
    url = _get_redis_test_url()
    client = Redis.from_url(url, decode_responses=False)
    await client.ping()
    yield client
    await client.delete(test_stream_name)
    await client.aclose()


@pytest.fixture
def stream_client(redis_client: Redis) -> StreamClient:
    """Create a StreamClient wrapping the real Redis connection."""
    return StreamClient(redis_client)
