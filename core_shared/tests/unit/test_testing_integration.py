"""Unit tests for the shared worker *integration* test helpers in
``core_shared.testing.integration`` (ITER14-005 Phase 2).

These cover only the pure helpers that need no database — the DB fixtures
themselves (``async_engine``, ``async_connection``, ``db_session``,
``apply_migrations``) are exercised by each worker's integration suite, which is
where a real Docker Postgres is available.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core_shared.testing import integration


class TestGetRepoRoot:
    """``get_repo_root`` resolves the monorepo root from the module location."""

    def test_points_at_dir_with_backend_and_scripts(self) -> None:
        root = integration.get_repo_root()

        assert isinstance(root, Path)
        assert (root / "backend").is_dir()
        assert (root / "scripts" / "workspace_env.py").is_file()


class TestGetWorkspaceEnv:
    """``get_workspace_env`` shells out to ``scripts/workspace_env.py``."""

    def test_returns_parsed_json_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completed = subprocess.CompletedProcess(
            args=["python3"], returncode=0, stdout=json.dumps({"DB_TEST_PORT": "9999"})
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed)

        env = integration.get_workspace_env()

        assert env["DB_TEST_PORT"] == "9999"

    def test_raises_runtime_error_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> object:
            raise OSError("workspace_env exploded")

        monkeypatch.setattr(subprocess, "run", _boom)

        with pytest.raises(RuntimeError, match="workspace environment"):
            integration.get_workspace_env()


class TestGetAsyncDatabaseUrl:
    """``get_async_database_url`` yields an asyncpg DSN, honouring ``DATABASE_URL``."""

    def test_honours_explicit_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+asyncpg://u:p@localhost:5432/explicit_db",
        )

        assert (
            integration.get_async_database_url()
            == "postgresql+asyncpg://u:p@localhost:5432/explicit_db"
        )

    def test_normalises_sync_driver_to_asyncpg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/sync_db")

        assert (
            integration.get_async_database_url()
            == "postgresql+asyncpg://u:p@localhost:5432/sync_db"
        )

    def test_falls_back_to_workspace_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(
            integration, "get_workspace_env", lambda: {"DB_TEST_PORT": "7654"}
        )

        url = integration.get_async_database_url()

        assert url.startswith("postgresql+asyncpg://")
        assert ":7654/" in url
