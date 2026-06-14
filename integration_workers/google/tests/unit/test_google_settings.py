"""
Unit tests for the Google worker settings (ITER14-001 Phase 2).

Verifies that ``GoogleSettings`` subclasses the shared ``BaseWorkerSettings``,
declares only Google-specific fields, inherits the common base fields/defaults,
overrides the per-worker identity defaults, and masks its secrets.

The package ``tests/conftest.py`` seeds several env vars (DATABASE_URL,
WORKER_ID, ...) for module collection. Tests that assert *defaults* therefore
clear those names first via the ``clean_env`` fixture so the subclass defaults
are observed rather than the conftest values.
"""

from __future__ import annotations

import pytest
from core_shared.worker_settings import BaseWorkerSettings
from pydantic import SecretStr, ValidationError

from google_settings import GoogleSettings

_DB_URL = "postgresql://user:pw@dbhost:5432/pms"
_CLIENT_SECRET = "google-secret-value"  # noqa: S105
_ENCRYPTION_KEY = "encryption-key-value"  # noqa: S105

# Env names the conftest seeds or that the base/subclass read; cleared so
# default-assertion tests are not masked by ambient values.
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
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "ENCRYPTION_KEY",
    "MAX_CONCURRENT_JOBS",
    "GOOGLE_RESERVED_GROUPS",
    "WEBHOOK_BASE_URL",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient worker env vars so subclass defaults are observable."""
    for name in _MANAGED_ENV:
        monkeypatch.delenv(name, raising=False)


def _make_settings(**overrides: object) -> GoogleSettings:
    """Build a GoogleSettings with the required fields, ignoring any .env file."""
    kwargs: dict[str, object] = {
        "database_url": SecretStr(_DB_URL),
        "google_client_id": "google-client-id",
        "google_client_secret": SecretStr(_CLIENT_SECRET),
        "encryption_key": SecretStr(_ENCRYPTION_KEY),
        "_env_file": None,
    }
    kwargs.update(overrides)
    return GoogleSettings(**kwargs)  # type: ignore[arg-type]


def test_subclasses_base_worker_settings() -> None:
    """GoogleSettings is a BaseWorkerSettings subclass (shares the common base)."""
    assert issubclass(GoogleSettings, BaseWorkerSettings)


def test_loads_google_specific_fields_from_kwargs(clean_env: None) -> None:
    """Integration-specific fields are accepted and exposed."""
    settings = _make_settings(
        google_client_id="cid",
        max_concurrent_jobs=9,
        google_reserved_groups=["myContacts", "starred"],
        webhook_base_url="https://hooks.example.com",
    )

    assert settings.google_client_id == "cid"
    assert settings.google_client_secret.get_secret_value() == _CLIENT_SECRET
    assert settings.encryption_key.get_secret_value() == _ENCRYPTION_KEY
    assert settings.max_concurrent_jobs == 9
    assert settings.google_reserved_groups == ["myContacts", "starred"]
    assert settings.webhook_base_url == "https://hooks.example.com"


def test_google_specific_defaults(clean_env: None) -> None:
    """Google-specific fields fall back to their documented defaults."""
    settings = _make_settings()

    assert settings.max_concurrent_jobs == 5
    assert settings.google_reserved_groups == ["myContacts"]
    assert settings.webhook_base_url == ""


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

    assert settings.worker_id == "google-worker"
    assert settings.otel_service_name == "google-worker"


def test_secrets_are_masked(clean_env: None) -> None:
    """All secrets are SecretStr: masked in repr/str, raw via accessor."""
    settings = _make_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.google_client_secret, SecretStr)
    assert isinstance(settings.encryption_key, SecretStr)
    rendered = repr(settings) + str(settings)
    assert "pw" not in rendered
    assert _CLIENT_SECRET not in rendered
    assert _ENCRYPTION_KEY not in rendered


def test_loads_from_env_vars(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration-specific and base fields load from environment variables."""
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", _CLIENT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", _ENCRYPTION_KEY)
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "11")
    monkeypatch.setenv("WEBHOOK_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("REDIS_URL", "redis://other:6380/2")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = GoogleSettings(_env_file=None)

    assert settings.google_client_id == "env-cid"
    assert settings.google_client_secret.get_secret_value() == _CLIENT_SECRET
    assert settings.max_concurrent_jobs == 11
    assert settings.webhook_base_url == "https://env.example.com"
    assert settings.redis_url == "redis://other:6380/2"
    assert settings.log_level == "DEBUG"
    # Identity defaults still apply when their env vars are unset.
    assert settings.worker_id == "google-worker"


def test_missing_required_field_raises(clean_env: None) -> None:
    """Required Google fields raise a ValidationError when absent."""
    partial_kwargs: dict[str, object] = {
        "database_url": SecretStr(_DB_URL),
        "_env_file": None,
    }
    with pytest.raises(ValidationError) as exc_info:
        GoogleSettings(**partial_kwargs)  # type: ignore[arg-type]

    message = str(exc_info.value)
    assert "google_client_id" in message
