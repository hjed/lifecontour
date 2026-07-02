"""Governance test: the integration workers share one tooling configuration.

ITER14-005 Phase 3 removes per-worker scaffolding duplication. Rather than each
worker repeating the same ruff/mypy/pytest/coverage config in its own
``pyproject.toml``, the shared base config lives once at the repo root
(``ruff.toml``, ``mypy.ini``, ``pytest.ini``) and every worker consumes it. The
canonical worker ``Dockerfile`` pattern is likewise identical across workers.

This is a meta/governance test (not a feature test): it parses the four worker
``pyproject.toml`` files and ``Dockerfile``s and asserts they stay trimmed and
conformant, so the duplication cannot silently creep back in.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

# core_shared/tests/unit/<this file> -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
WORKERS_DIR = REPO_ROOT / "integration_workers"
WORKERS = ["google", "immich", "strava", "snipeit"]

pytestmark = pytest.mark.skipif(
    not WORKERS_DIR.is_dir(),
    reason="integration_workers/ not present (isolated core_shared checkout)",
)


def _load_pyproject(worker: str) -> dict[str, Any]:
    path = WORKERS_DIR / worker / "pyproject.toml"
    assert path.is_file(), f"missing {path}"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _read_dockerfile(worker: str) -> str:
    path = WORKERS_DIR / worker / "Dockerfile"
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("worker", WORKERS)
class TestWorkerPyprojectTrimmed:
    """Each worker pyproject inherits shared tooling and repeats none of it."""

    def test_no_inline_mypy_config(self, worker: str) -> None:
        tool = _load_pyproject(worker).get("tool", {})
        assert "mypy" not in tool, (
            f"{worker}: [tool.mypy] must live in the shared root mypy.ini"
        )
        assert "pydantic-mypy" not in tool, (
            f"{worker}: [tool.pydantic-mypy] must live in the shared root mypy.ini"
        )

    def test_no_inline_pytest_config(self, worker: str) -> None:
        tool = _load_pyproject(worker).get("tool", {})
        assert "pytest" not in tool, (
            f"{worker}: [tool.pytest.ini_options] must live in the shared root pytest.ini"
        )

    def test_no_inline_coverage_config(self, worker: str) -> None:
        tool = _load_pyproject(worker).get("tool", {})
        assert "coverage" not in tool, (
            f"{worker}: worker coverage config is dead; drop it from pyproject.toml"
        )

    def test_ruff_extends_shared_config(self, worker: str) -> None:
        ruff = _load_pyproject(worker).get("tool", {}).get("ruff", {})
        assert ruff.get("extend") == "../../ruff.toml", (
            f"{worker}: [tool.ruff] must extend the shared ../../ruff.toml"
        )
        # Note: the worker keeps a small [tool.ruff.lint.extend-per-file-ignores]
        # because ruff anchors per-file-ignore globs to the config file's own
        # directory, so the root ruff.toml patterns do not reach the worker's
        # tests/. This is a legitimate per-worker override, not duplicated config.

    def test_requires_python_pinned(self, worker: str) -> None:
        project = _load_pyproject(worker).get("project", {})
        assert project.get("requires-python") == ">=3.14", (
            f"{worker}: requires-python must be >=3.14"
        )

    def test_core_shared_editable_source(self, worker: str) -> None:
        sources = (
            _load_pyproject(worker).get("tool", {}).get("uv", {}).get("sources", {})
        )
        core_shared = sources.get("core_shared", {})
        assert core_shared.get("editable") is True, (
            f"{worker}: core_shared must be an editable path source"
        )


@pytest.mark.unit
@pytest.mark.parametrize("worker", WORKERS)
class TestWorkerDockerfileCanonical:
    """Each worker Dockerfile conforms to the canonical pattern."""

    def test_from_shared_base_image(self, worker: str) -> None:
        assert "FROM pms-python-base" in _read_dockerfile(worker)

    def test_healthcheck_uses_os_environ(self, worker: str) -> None:
        content = _read_dockerfile(worker)
        assert "os.environ['REDIS_URL']" in content, (
            f"{worker}: HEALTHCHECK must read REDIS_URL via os.environ, not a bare shell var"
        )
        assert "${REDIS_URL}" not in content, (
            f"{worker}: HEALTHCHECK must not use bare ${{REDIS_URL}}"
        )

    def test_copy_before_install(self, worker: str) -> None:
        content = _read_dockerfile(worker)
        # Use find() (not index()) so a missing marker fails as a readable
        # assertion rather than a raised ValueError.
        pyproject_copy = content.find(
            f"COPY ./integration_workers/{worker}/pyproject.toml"
        )
        source_copy = content.find(f"COPY ./integration_workers/{worker}/ .")
        install = content.find("uv pip install --system --no-cache-dir --no-sources .")
        assert pyproject_copy != -1, f"{worker}: missing COPY of pyproject.toml"
        assert source_copy != -1, f"{worker}: missing COPY of worker source"
        assert install != -1, f"{worker}: missing 'uv pip install … --no-sources .'"
        assert pyproject_copy < source_copy < install, (
            f"{worker}: must COPY pyproject, then source, then install"
        )

    def test_runs_as_appuser(self, worker: str) -> None:
        assert "USER appuser" in _read_dockerfile(worker)

    def test_cmd_runs_worker(self, worker: str) -> None:
        assert 'CMD ["python", "worker.py"]' in _read_dockerfile(worker)
