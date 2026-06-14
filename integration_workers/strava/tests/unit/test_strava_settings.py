"""
Unit tests for the Strava worker settings (ITER14-001 Phase 2).

Verifies that ``StravaSettings`` subclasses the shared ``BaseWorkerSettings``,
declares only Strava-specific fields, inherits the common base fields/defaults,
overrides the per-worker identity defaults, and masks its secrets.

Strava has no package-level ``tests/conftest.py`` seeding env vars, but ambient
worker env vars are still cleared via ``clean_env`` so default-assertion tests
observe the subclass defaults deterministically.
"""

from __future__ import annotations

import pytest
from core_shared.worker_settings import BaseWorkerSettings
from pydantic import SecretStr, ValidationError

from strava_settings import StravaSettings

_DB_URL = "postgresql://user:pw@dbhost:5432/pms"
_CLIENT_SECRET = "strava-secret-value"  # noqa: S105
_ENCRYPTION_KEY = "encryption-key-value"  # noqa: S105

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
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "ENCRYPTION_KEY",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient worker env vars so subclass defaults are observable."""
    for name in _MANAGED_ENV:
        monkeypatch.delenv(name, raising=False)


def _make_settings(**overrides: object) -> StravaSettings:
    """Build a StravaSettings with the required fields, ignoring any .env file."""
    kwargs: dict[str, object] = {
        "database_url": SecretStr(_DB_URL),
        "strava_client_id": "strava-client-id",
        "strava_client_secret": SecretStr(_CLIENT_SECRET),
        "encryption_key": SecretStr(_ENCRYPTION_KEY),
        "_env_file": None,
    }
    kwargs.update(overrides)
    return StravaSettings(**kwargs)  # type: ignore[arg-type]


def test_subclasses_base_worker_settings() -> None:
    """StravaSettings is a BaseWorkerSettings subclass (shares the common base)."""
    assert issubclass(StravaSettings, BaseWorkerSettings)


def test_loads_strava_specific_fields_from_kwargs(clean_env: None) -> None:
    """Integration-specific fields are accepted and exposed."""
    settings = _make_settings(strava_client_id="cid")

    assert settings.strava_client_id == "cid"
    assert settings.strava_client_secret.get_secret_value() == _CLIENT_SECRET
    assert settings.encryption_key.get_secret_value() == _ENCRYPTION_KEY


def test_inherits_base_defaults(clean_env: None) -> None:
    """Common base fields keep their inherited defaults when unset."""
    settings = _make_settings()

    assert settings.redis_url == "redis://redis:6379"
    assert settings.stream_name == "pms:domain-events"
    assert settings.queue_name == "arq:queue"
    assert settings.log_level == "INFO"
    assert settings.enable_periodic_sync is False
    assert settings.sync_interval_hours == 6
    assert settings.enable_telemetry is False
    assert settings.otel_exporter_otlp_endpoint == ""
    assert settings.otel_resource_attributes == ""


def test_per_worker_identity_overrides(clean_env: None) -> None:
    """worker_id and otel_service_name override the generic base defaults."""
    settings = _make_settings()

    assert settings.worker_id == "strava-worker"
    assert settings.otel_service_name == "strava-worker"


def test_secrets_are_masked(clean_env: None) -> None:
    """All secrets are SecretStr: masked in repr/str, raw via accessor."""
    settings = _make_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.strava_client_secret, SecretStr)
    assert isinstance(settings.encryption_key, SecretStr)
    rendered = repr(settings) + str(settings)
    assert "pw" not in rendered
    assert _CLIENT_SECRET not in rendered
    assert _ENCRYPTION_KEY not in rendered


def test_loads_from_env_vars(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration-specific and base fields load from environment variables."""
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    monkeypatch.setenv("STRAVA_CLIENT_ID", "env-cid")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", _CLIENT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", _ENCRYPTION_KEY)
    monkeypatch.setenv("REDIS_URL", "redis://other:6380/2")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = StravaSettings(_env_file=None)

    assert settings.strava_client_id == "env-cid"
    assert settings.strava_client_secret.get_secret_value() == _CLIENT_SECRET
    assert settings.redis_url == "redis://other:6380/2"
    assert settings.log_level == "DEBUG"
    # Identity defaults still apply when their env vars are unset.
    assert settings.worker_id == "strava-worker"


def test_missing_required_field_raises(clean_env: None) -> None:
    """Required Strava fields raise a ValidationError when absent."""
    partial_kwargs: dict[str, object] = {
        "database_url": SecretStr(_DB_URL),
        "_env_file": None,
    }
    with pytest.raises(ValidationError) as exc_info:
        StravaSettings(**partial_kwargs)  # type: ignore[arg-type]

    message = str(exc_info.value)
    assert "strava_client_id" in message
