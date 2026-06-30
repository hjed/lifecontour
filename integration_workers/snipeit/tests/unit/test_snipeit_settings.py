"""
Unit tests for the Snipe-IT worker settings (ITER14-001 Phase 3).

Verifies that ``SnipeItWorkerSettings`` subclasses the shared
``BaseWorkerSettings``, declares only Snipe-IT-specific fields, inherits the
common base fields/defaults (including the periodic-sync fields it previously
lacked, default-disabled), overrides the per-worker identity defaults, and masks
its secrets (``database_url``, ``encryption_key``) as ``SecretStr``.

Ambient worker env vars are cleared via ``clean_env`` so default-assertion tests
observe the subclass defaults deterministically.
"""

from __future__ import annotations

import pytest
from core_shared.testing import make_worker_settings
from core_shared.worker_settings import BaseWorkerSettings
from pydantic import SecretStr, ValidationError

from snipeit_settings import SnipeItWorkerSettings

_DB_URL = "postgresql://user:pw@dbhost:5432/pms"
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
    "ENCRYPTION_KEY",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient worker env vars so subclass defaults are observable."""
    for name in _MANAGED_ENV:
        monkeypatch.delenv(name, raising=False)


def _make_settings(**overrides: object) -> SnipeItWorkerSettings:
    """Build a SnipeItWorkerSettings with required fields, ignoring any .env."""
    kwargs: dict[str, object] = {
        "database_url": SecretStr(_DB_URL),
        "encryption_key": SecretStr(_ENCRYPTION_KEY),
    }
    kwargs.update(overrides)
    return make_worker_settings(SnipeItWorkerSettings, **kwargs)


def test_subclasses_base_worker_settings() -> None:
    """SnipeItWorkerSettings is a BaseWorkerSettings subclass (shared base)."""
    assert issubclass(SnipeItWorkerSettings, BaseWorkerSettings)


def test_loads_snipeit_specific_fields_from_kwargs(clean_env: None) -> None:
    """Integration-specific fields are accepted and exposed."""
    settings = _make_settings()

    assert settings.encryption_key.get_secret_value() == _ENCRYPTION_KEY


def test_encryption_key_defaults_to_empty(clean_env: None) -> None:
    """encryption_key defaults to an empty SecretStr (behaviour preserved)."""
    settings = _make_settings(encryption_key=SecretStr(""))

    assert settings.encryption_key.get_secret_value() == ""


def test_inherits_base_defaults(clean_env: None) -> None:
    """Common base fields keep their inherited defaults when unset."""
    settings = _make_settings()

    assert settings.redis_url == "redis://redis:6379"
    assert settings.stream_name == "pms:domain-events"
    assert settings.log_level == "INFO"
    assert settings.enable_telemetry is False
    assert settings.otel_exporter_otlp_endpoint == ""
    assert settings.otel_resource_attributes == ""


def test_inherits_periodic_sync_fields_disabled(clean_env: None) -> None:
    """snipeit gains the inherited periodic-sync fields, default-disabled.

    snipeit previously declared no periodic-sync fields. After rebasing onto
    BaseWorkerSettings they are inherited and default to disabled, so scheduling
    behaviour is unchanged.
    """
    settings = _make_settings()

    assert settings.enable_periodic_sync is False
    assert settings.sync_interval_hours == 6


def test_per_worker_identity_overrides(clean_env: None) -> None:
    """worker_id, queue_name and otel_service_name override the base defaults."""
    settings = _make_settings()

    assert settings.worker_id == "snipeit-worker"
    assert settings.queue_name == "arq:snipeit"
    assert settings.otel_service_name == "snipeit-worker"


def test_secrets_are_masked(clean_env: None) -> None:
    """All secrets are SecretStr: masked in repr/str, raw via accessor."""
    settings = _make_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.encryption_key, SecretStr)
    rendered = repr(settings) + str(settings)
    assert "pw" not in rendered
    assert _ENCRYPTION_KEY not in rendered


def test_secret_call_sites_resolve_raw_value(clean_env: None) -> None:
    """`.get_secret_value()` returns the raw DSN / encryption key for call sites."""
    settings = _make_settings()

    assert settings.database_url.get_secret_value() == _DB_URL
    assert settings.encryption_key.get_secret_value() == _ENCRYPTION_KEY


def test_loads_from_env_vars(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration-specific and base fields load from environment variables."""
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    monkeypatch.setenv("ENCRYPTION_KEY", _ENCRYPTION_KEY)
    monkeypatch.setenv("REDIS_URL", "redis://other:6380/2")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = SnipeItWorkerSettings(_env_file=None)

    assert settings.database_url.get_secret_value() == _DB_URL
    assert settings.encryption_key.get_secret_value() == _ENCRYPTION_KEY
    assert settings.redis_url == "redis://other:6380/2"
    assert settings.log_level == "DEBUG"
    # Identity defaults still apply when their env vars are unset.
    assert settings.worker_id == "snipeit-worker"


def test_missing_required_field_raises(clean_env: None) -> None:
    """The required database_url field raises a ValidationError when absent."""
    with pytest.raises(ValidationError) as exc_info:
        SnipeItWorkerSettings(_env_file=None)

    assert "database_url" in str(exc_info.value)
