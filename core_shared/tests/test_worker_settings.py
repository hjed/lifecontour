"""
Unit tests for the shared worker settings base and Redis-settings helper.

Covers ITER14-001 Phase 1: ``BaseWorkerSettings`` field defaults, env-var
loading, ``SecretStr`` masking of ``database_url``, and the
``redis_settings_from_url`` helper (consolidating the duplicated
``_parse_redis_url`` copies in the immich/snipeit workers).
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from arq.connections import RedisSettings
from pydantic import SecretStr, ValidationError

from core_shared.worker_settings import BaseWorkerSettings, redis_settings_from_url

# A representative database URL used across the tests. ``_env_file=None`` is
# passed on every instantiation so a developer's local ``core_shared/.env``
# cannot leak values and mask the required-field assertions.
_DB_URL = "postgresql://user:pw@dbhost:5432/pms"


def _legacy_parse_redis_url(url: str) -> RedisSettings:
    """The original copy-pasted immich/snipeit parser, used here as an oracle.

    Mirrors ``_parse_redis_url`` in ``integration_workers/immich/worker.py`` and
    ``integration_workers/snipeit/worker.py`` so we can assert the shared helper
    is behaviour-preserving before those copies are deleted in Phase 2.
    """
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


# ---------------------------------------------------------------------------
# BaseWorkerSettings — defaults
# ---------------------------------------------------------------------------


def test_defaults_when_only_required_provided() -> None:
    """All non-required fields fall back to their documented defaults."""
    settings = BaseWorkerSettings(database_url=SecretStr(_DB_URL), _env_file=None)

    assert settings.redis_url == "redis://redis:6379"
    assert settings.stream_name == "pms:domain-events"
    assert settings.worker_id == "worker"
    assert settings.queue_name == "arq:queue"
    assert settings.log_level == "INFO"
    assert settings.enable_periodic_sync is False
    assert settings.sync_interval_hours == 6
    assert settings.enable_telemetry is False
    assert settings.otel_exporter_otlp_endpoint == ""
    assert settings.otel_service_name == "worker"
    assert settings.otel_resource_attributes == ""


def test_queue_name_default_matches_arq_default() -> None:
    """The default queue name matches arq's own default so wiring is inert.

    arq's ``default_queue_name`` is ``"arq:queue"``; google/strava rely on it
    today, so this default is behaviourally inert when they subclass the base.
    """
    settings = BaseWorkerSettings(database_url=SecretStr(_DB_URL), _env_file=None)
    assert settings.queue_name == "arq:queue"


# ---------------------------------------------------------------------------
# BaseWorkerSettings — required field
# ---------------------------------------------------------------------------


def test_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``database_url`` is required; absence raises a ValidationError."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        BaseWorkerSettings(_env_file=None)

    assert "database_url" in str(exc_info.value)


# ---------------------------------------------------------------------------
# BaseWorkerSettings — env-var loading and coercion
# ---------------------------------------------------------------------------


def test_loads_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fields load from environment variables with bool/int coercion."""
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    monkeypatch.setenv("REDIS_URL", "redis://other:6380/2")
    monkeypatch.setenv("STREAM_NAME", "custom:stream")
    monkeypatch.setenv("WORKER_ID", "x-worker")
    monkeypatch.setenv("QUEUE_NAME", "arq:x")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ENABLE_PERIODIC_SYNC", "true")
    monkeypatch.setenv("SYNC_INTERVAL_HOURS", "12")
    monkeypatch.setenv("ENABLE_TELEMETRY", "true")

    settings = BaseWorkerSettings(_env_file=None)

    assert settings.database_url.get_secret_value() == _DB_URL
    assert settings.redis_url == "redis://other:6380/2"
    assert settings.stream_name == "custom:stream"
    assert settings.worker_id == "x-worker"
    assert settings.queue_name == "arq:x"
    assert settings.log_level == "DEBUG"
    assert settings.enable_periodic_sync is True
    assert settings.sync_interval_hours == 12
    assert settings.enable_telemetry is True


def test_env_vars_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lower/mixed-case env names load (case_sensitive=False)."""
    monkeypatch.setenv("database_url", _DB_URL)
    monkeypatch.setenv("Redis_Url", "redis://mixed:6381/1")

    settings = BaseWorkerSettings(_env_file=None)

    assert settings.database_url.get_secret_value() == _DB_URL
    assert settings.redis_url == "redis://mixed:6381/1"


def test_extra_env_vars_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrelated env vars do not break construction (extra='ignore')."""
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    monkeypatch.setenv("SOME_UNRELATED_VAR", "should-be-ignored")

    settings = BaseWorkerSettings(_env_file=None)

    assert settings.database_url.get_secret_value() == _DB_URL


# ---------------------------------------------------------------------------
# BaseWorkerSettings — SecretStr masking
# ---------------------------------------------------------------------------


def test_database_url_is_secretstr_masked() -> None:
    """The database URL is a SecretStr: masked in repr/str, raw via accessor."""
    settings = BaseWorkerSettings(database_url=SecretStr(_DB_URL), _env_file=None)

    assert isinstance(settings.database_url, SecretStr)
    assert "pw" not in repr(settings)
    assert "pw" not in str(settings)
    assert "pw" not in repr(settings.database_url)
    assert settings.database_url.get_secret_value() == _DB_URL


# ---------------------------------------------------------------------------
# redis_settings_from_url
# ---------------------------------------------------------------------------


def test_redis_settings_returns_redissettings_type() -> None:
    """The helper returns an arq RedisSettings instance."""
    result = redis_settings_from_url("redis://redis:6379")
    assert isinstance(result, RedisSettings)


def test_redis_settings_with_db_index() -> None:
    """A redis URL with a db index parses host/port/database."""
    result = redis_settings_from_url("redis://host:6380/3")
    assert result.host == "host"
    assert result.port == 6380
    assert result.database == 3


def test_redis_settings_without_db_index() -> None:
    """A redis URL without a db index defaults database to 0."""
    result = redis_settings_from_url("redis://host:6380")
    assert result.host == "host"
    assert result.port == 6380
    assert result.database == 0


def test_redis_settings_with_password() -> None:
    """A redis URL with credentials extracts the password."""
    result = redis_settings_from_url("redis://user:secret@host:6379/1")
    assert result.host == "host"
    assert result.database == 1
    assert result.password == "secret"


def test_redis_settings_without_password() -> None:
    """A redis URL without credentials yields no password."""
    result = redis_settings_from_url("redis://host:6379/0")
    assert result.password is None


def test_redis_settings_host_port_extraction() -> None:
    """Host and port are extracted from the authority component."""
    result = redis_settings_from_url("redis://myhost:1234/0")
    assert result.host == "myhost"
    assert result.port == 1234


def test_redis_settings_default_url_round_trips() -> None:
    """The default redis_url derives a sensible RedisSettings."""
    settings = BaseWorkerSettings(database_url=SecretStr(_DB_URL), _env_file=None)
    result = redis_settings_from_url(settings.redis_url)

    assert result.host == "redis"
    assert result.port == 6379
    assert result.database == 0
    assert result.password is None


@pytest.mark.parametrize(
    "url",
    [
        "redis://host:6380/3",
        "redis://host:6380",
        "redis://user:secret@host:6379/1",
        "redis://host:6379/0",
        "redis://redis:6379",
    ],
)
def test_matches_legacy_parse_behaviour(url: str) -> None:
    """The shared helper is behaviour-equivalent to the legacy parser.

    Guards the Phase-2 deletion of the duplicated immich/snipeit
    ``_parse_redis_url`` helpers.
    """
    new = redis_settings_from_url(url)
    old = _legacy_parse_redis_url(url)

    assert new.host == old.host
    assert new.port == old.port
    assert new.database == old.database
    assert new.password == old.password


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


def test_exported_from_core_shared() -> None:
    """Both symbols are re-exported from the top-level package."""
    import core_shared

    assert core_shared.BaseWorkerSettings is BaseWorkerSettings
    assert core_shared.redis_settings_from_url is redis_settings_from_url
    assert "BaseWorkerSettings" in core_shared.__all__
    assert "redis_settings_from_url" in core_shared.__all__
