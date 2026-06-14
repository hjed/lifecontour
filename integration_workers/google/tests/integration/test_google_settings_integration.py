"""
Integration test: the Google worker boots from a representative ``.env`` and
resolves its Redis + database URLs correctly (ITER14-001 Phase 2).

Behaviour-preservation check for the settings migration onto
``BaseWorkerSettings``:

1. ``GoogleSettings`` loads a representative ``.env`` file and resolves the
   database + Redis URLs (the boot-config path).
2. The already-imported worker module derives its ARQ ``redis_settings`` via the
   shared ``redis_settings_from_url`` helper from its own settings — asserted
   self-consistently so the check is independent of test/import ordering.

The worker module is imported normally (never reloaded) so this test does not
perturb the shared module state other integration tests rely on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core_shared.worker_settings import redis_settings_from_url

from google_settings import GoogleSettings

_DB_URL = "postgresql://postgres:postgres@localhost:5432/personal_management"
_REDIS_URL = "redis://localhost:6379/0"
_REPRESENTATIVE_ENV = f"""\
DATABASE_URL={_DB_URL}
REDIS_URL={_REDIS_URL}
GOOGLE_CLIENT_ID=test_google_client_id
GOOGLE_CLIENT_SECRET=test_google_client_secret
ENCRYPTION_KEY=test_encryption_key_32_characters!
"""

# Env names cleared so the .env file is the resolution source, not ambient vars
# seeded by the package conftest.
_MANAGED_ENV = (
    "DATABASE_URL",
    "REDIS_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "ENCRYPTION_KEY",
    "WORKER_ID",
    "LOG_LEVEL",
)


def test_boots_from_representative_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GoogleSettings loads a representative .env and resolves DB + Redis URLs."""
    for name in _MANAGED_ENV:
        monkeypatch.delenv(name, raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(_REPRESENTATIVE_ENV)

    settings = GoogleSettings(_env_file=str(env_path))

    assert settings.database_url.get_secret_value() == _DB_URL
    assert settings.redis_url == _REDIS_URL
    assert settings.worker_id == "google-worker"

    redis_settings = redis_settings_from_url(settings.redis_url)
    assert redis_settings.host == "localhost"
    assert redis_settings.port == 6379
    assert redis_settings.database == 0


def test_arq_redis_settings_derived_via_shared_helper() -> None:
    """The ARQ worker class derives Redis settings via the shared helper."""
    import worker  # cached import; env provided by the package conftest.

    expected = redis_settings_from_url(worker.settings.redis_url)
    actual = worker.GoogleWorkerSettings.redis_settings
    assert actual.host == expected.host
    assert actual.port == expected.port
    assert actual.database == expected.database
    assert actual.password == expected.password


def test_arq_max_jobs_wired_from_settings() -> None:
    """The ARQ concurrency limit is sourced from the migrated settings."""
    import worker

    assert worker.GoogleWorkerSettings.max_jobs == worker.settings.max_concurrent_jobs
