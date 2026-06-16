"""
Integration test: the Immich worker boots from a representative ``.env`` and
resolves its Redis + database URLs correctly (ITER14-001 Phase 3).

Behaviour-preservation check for the settings migration onto
``BaseWorkerSettings`` + ``SecretStr``:

1. ``ImmichWorkerSettings`` loads a representative ``.env`` file and resolves the
   database (via ``SecretStr.get_secret_value()``) + Redis URLs (the boot-config
   path).
2. The already-imported worker module resolves its ARQ ``redis_settings`` via the
   worker's own ``_parse_redis_url`` helper — asserted self-consistently so the
   check is independent of test/import ordering. (Replacing ``_parse_redis_url``
   with the shared helper is ITER14-002, not this phase.)

The required worker env is seeded at module import so ``import worker`` succeeds,
and the worker module is imported normally (never reloaded) so this test does not
perturb the shared module state other integration tests rely on.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from core_shared.worker_settings import redis_settings_from_url

from .conftest import get_async_database_url

# Seed the required worker env so importing the real worker module succeeds.
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ9")
os.environ.setdefault("DATABASE_URL", get_async_database_url())

from immich_settings import ImmichWorkerSettings  # noqa: E402

_DB_URL = "postgresql://postgres:postgres@localhost:5432/personal_management"
_REDIS_URL = "redis://localhost:6379/0"
_REPRESENTATIVE_ENV = f"""\
DATABASE_URL={_DB_URL}
REDIS_URL={_REDIS_URL}
ENCRYPTION_KEY=dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ9
"""

# Env names cleared so the .env file is the resolution source, not ambient vars.
_MANAGED_ENV = (
    "DATABASE_URL",
    "REDIS_URL",
    "ENCRYPTION_KEY",
    "WORKER_ID",
    "LOG_LEVEL",
)


def test_boots_from_representative_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ImmichWorkerSettings loads a representative .env and resolves DB + Redis."""
    for name in _MANAGED_ENV:
        monkeypatch.delenv(name, raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(_REPRESENTATIVE_ENV)

    settings = ImmichWorkerSettings(_env_file=str(env_path))

    assert settings.database_url.get_secret_value() == _DB_URL
    assert settings.redis_url == _REDIS_URL
    assert settings.worker_id == "immich-worker"

    redis_settings = redis_settings_from_url(settings.redis_url)
    assert redis_settings.host == "localhost"
    assert redis_settings.port == 6379
    assert redis_settings.database == 0


def test_arq_redis_settings_match_configured_redis_url() -> None:
    """The ARQ worker class derives Redis settings from its own settings."""
    import worker

    expected = redis_settings_from_url(worker.settings.redis_url)
    actual = worker.WorkerSettings.redis_settings
    assert actual.host == expected.host
    assert actual.port == expected.port
    assert actual.database == expected.database
    assert actual.password == expected.password
