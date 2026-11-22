"""Every Python install in the images and CI comes from a ``uv.lock``.

A meta/governance test, like ``test_worker_tooling_standardisation.py``: it
reads the Dockerfiles and workflow files as text and asserts that no install
resolves dependencies afresh from ``pyproject.toml``. A fresh resolution is how
production and CI drifted from the lock (a new SQLAlchemy release broke the
backend image before the lock had seen it), so an unlocked install must not
creep back in.

The installs this enforces:

- Docker: ``uv export --locked`` writes the lock to a requirements file,
  ``uv pip install -r`` installs it, and the project itself is installed with
  ``--no-deps``. ``--locked`` fails the build when the lock is stale.
- CI: ``uv sync --locked`` (also fails on a stale lock), and a ``python-locks``
  job that runs ``uv lock --check`` for every project.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# core_shared/tests/unit/<this file> -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
WORKERS = ["google", "immich", "strava", "snipeit"]

BASE_DOCKERFILE = Path("docker/python-base/Dockerfile")
BACKEND_DOCKERFILE = Path("docker/backend/Dockerfile")
WORKER_DOCKERFILES = [Path(f"integration_workers/{w}/Dockerfile") for w in WORKERS]
DOCKERFILES = [BASE_DOCKERFILE, BACKEND_DOCKERFILE, *WORKER_DOCKERFILES]

CI_WORKFLOW = Path(".github/workflows/ci.yml")
SECURITY_WORKFLOW = Path(".github/workflows/security.yml")
WORKFLOWS = [CI_WORKFLOW, SECURITY_WORKFLOW]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        not (REPO_ROOT / BACKEND_DOCKERFILE).is_file(),
        reason="repo-root Dockerfiles not present (isolated core_shared checkout)",
    ),
]


def _read(relative: Path) -> str:
    path = REPO_ROOT / relative
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def _shell_commands(dockerfile: str) -> list[str]:
    """Each simple command of every ``RUN`` instruction, continuations joined.

    ``RUN a && b; c`` yields ``["a", "b", "c"]``, so a flag on one command
    can't be credited to its neighbour.
    """
    logical = re.sub(r"\\\n", " ", dockerfile)
    commands: list[str] = []
    for line in logical.splitlines():
        stripped = line.strip()
        if not stripped.startswith("RUN "):
            continue
        for command in re.split(r"&&|;|\|\|", stripped.removeprefix("RUN ")):
            command = " ".join(command.split())
            if command:
                commands.append(command)
    return commands


def _commands_running(dockerfile: str, program: str) -> list[str]:
    return [c for c in _shell_commands(dockerfile) if program in c]


def _locked_projects() -> list[Path]:
    """Every project directory that commits a ``uv.lock``."""
    return sorted(
        lock.parent.relative_to(REPO_ROOT)
        for pattern in ("*/uv.lock", "integration_workers/*/uv.lock")
        for lock in REPO_ROOT.glob(pattern)
    )


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=str)
class TestDockerfilesInstallFromTheLock:
    def test_exports_its_lock(self, dockerfile: Path) -> None:
        exports = _commands_running(_read(dockerfile), "uv export")
        assert exports, f"{dockerfile}: must install from `uv export` of its lock"
        for export in exports:
            assert "--locked" in export, (
                f"{dockerfile}: `{export}` must pass --locked so a stale lock fails"
            )

    def test_exports_skip_the_project_and_core_shared(self, dockerfile: Path) -> None:
        # The project is installed separately with --no-deps, and core_shared
        # is already installed editable by the base image.
        for export in _commands_running(_read(dockerfile), "uv export"):
            assert "--no-emit-project" in export, f"{dockerfile}: `{export}`"
            if dockerfile != BASE_DOCKERFILE:
                assert "--no-emit-package core_shared" in export, (
                    f"{dockerfile}: `{export}`"
                )

    def test_every_install_skips_resolution(self, dockerfile: Path) -> None:
        """Every install passes --no-deps, so only the lock picks versions.

        Without it, ``uv pip install .`` or ``uv pip install watchdog`` resolves
        afresh, and even ``-r <export>`` re-resolves the closure: that drops the
        lock's ``override-dependencies`` and fails the workers' build.
        """
        installs = _commands_running(_read(dockerfile), "uv pip install")
        assert installs, f"{dockerfile}: expected uv pip install commands"
        for install in installs:
            assert "--no-deps" in install, (
                f"{dockerfile}: `{install}` resolves dependencies outside the lock"
            )

    def test_installs_the_exported_requirements(self, dockerfile: Path) -> None:
        installs = _commands_running(_read(dockerfile), "uv pip install")
        assert any("-r /tmp/requirements.txt" in i for i in installs), (
            f"{dockerfile}: must install the exported lock"
        )


@pytest.mark.parametrize("dockerfile", [BASE_DOCKERFILE, *WORKER_DOCKERFILES], ids=str)
def test_production_only_images_skip_dev_dependencies(dockerfile: Path) -> None:
    for export in _commands_running(_read(dockerfile), "uv export"):
        assert "--no-dev" in export, (
            f"{dockerfile}: `{export}` would ship the dev dependency group"
        )


def test_backend_image_exports_dev_dependencies_only_when_asked() -> None:
    exports = _commands_running(_read(BACKEND_DOCKERFILE), "uv export")
    production = [e for e in exports if "--no-dev" in e]
    development = [e for e in exports if "--extra dev" in e]
    assert len(production) == 1, f"one production export expected, got {exports}"
    assert len(development) == 1, f"one development export expected, got {exports}"
    assert len(exports) == 2, f"unexpected exports: {exports}"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=str)
class TestWorkflowsInstallFromTheLock:
    def test_no_uv_pip_install(self, workflow: Path) -> None:
        offending = [
            line.strip()
            for line in _read(workflow).splitlines()
            if "uv pip install" in line
        ]
        assert not offending, (
            f"{workflow}: use `uv sync --locked` or `uvx`, not {offending}"
        )

    def test_every_uv_sync_is_locked(self, workflow: Path) -> None:
        unlocked = [
            line.strip()
            for line in _read(workflow).splitlines()
            if re.search(r"\buv sync\b", line) and "--locked" not in line
        ]
        assert not unlocked, f"{workflow}: `uv sync` without --locked: {unlocked}"


def test_pip_audit_reads_every_exported_lock() -> None:
    content = _read(SECURITY_WORKFLOW)
    audits = [line for line in content.splitlines() if "pip-audit" in line]
    assert any(" -r " in line for line in audits), (
        "security.yml: pip-audit must audit an exported lock (`-r`), not a "
        f"fresh resolution: {audits}"
    )
    assert "uv export -q --locked" in content
    unaudited = [str(p) for p in _locked_projects() if str(p) not in content]
    assert not unaudited, f"security.yml pip-audit does not cover {unaudited}"


def test_python_locks_job_checks_every_lock() -> None:
    content = _read(CI_WORKFLOW)
    match = re.search(
        r"^  python-locks:\n(?P<body>(?:    .*\n|\n)+)", content, re.MULTILINE
    )
    assert match, "ci.yml: missing the python-locks job"
    body = match["body"]
    assert "needs: changes" in body, "python-locks must sit behind the stack gate"
    assert "uv lock --check" in body
    projects = _locked_projects()
    assert Path("backend") in projects, f"lock discovery is broken: {projects}"
    unchecked = [str(p) for p in projects if str(p) not in body]
    assert not unchecked, f"python-locks does not check {unchecked}"
