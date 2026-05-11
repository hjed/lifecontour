import os

os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_management_test"
)
os.environ["ENCRYPTION_KEY"] = "testkey"

from arq.connections import RedisSettings

from worker import _parse_redis_url


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
