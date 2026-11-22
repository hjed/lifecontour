"""The sibling-lock relock is wired up safely.

Each backend and worker ``uv.lock`` records ``core_shared``'s requirements, so a
change to ``core_shared/pyproject.toml`` leaves five locks stale, and Dependabot
relocks only the directory it bumps. ``scripts/relock-python.sh`` relocks every
project. It runs from a pre-commit hook for local edits, and from
``relock-dependents.yml`` on Dependabot PRs.

That workflow is the only PR workflow holding a credential (a GitHub App key
stored as a Dependabot secret), so these governance checks pin down when it may
run: only for Dependabot's own same-repo PRs, never through
``pull_request_target``, and with no other secret; like the other governance
tests, those checks read the files as text. The script itself is exercised for
real, in a scratch git repo with a fake ``uv`` on ``PATH``.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

# core_shared/tests/unit/<this file> -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "relock-python.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "relock-dependents.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        not CI_WORKFLOW.is_file(),
        reason="repo-root workflows not present (isolated core_shared checkout)",
    ),
]


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def _block(content: str, header: str) -> str:
    """The lines indented under ``header`` (a line matched exactly, start to end)."""
    match = re.search(
        rf"^(?P<indent> *){re.escape(header)}\n(?P<body>(?:(?P=indent) +.*\n|\n)*)",
        content,
        re.MULTILINE,
    )
    assert match, f"missing `{header}`"
    return match["body"]


# A stand-in for `uv` that records each call and fails for the projects named
# in FAKE_UV_FAIL, so the script's discovery and error handling run for real
# without resolving anything.
FAKE_UV = """#!/usr/bin/env bash
directory=""
previous=""
for argument in "$@"; do
    [[ "$previous" == --directory ]] && directory="$argument"
    previous="$argument"
done
echo "$directory $*" >> "$FAKE_UV_LOG"
if [[ " ${FAKE_UV_FAIL:-} " == *" $directory "* ]]; then
    echo "fake uv: cannot lock $directory" >&2
    exit 1
fi
"""


@dataclass(frozen=True)
class Run:
    returncode: int
    output: str
    uv_calls: list[str]


@dataclass(frozen=True)
class ScratchRepo:
    root: Path
    bin_dir: Path

    def run(self, *args: str, fail: str = "", github_actions: bool = False) -> Run:
        log = self.root.parent / "uv-calls.log"
        log.unlink(missing_ok=True)
        env = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_UV_LOG": str(log),
            "FAKE_UV_FAIL": fail,
        }
        env.pop("GITHUB_ACTIONS", None)
        if github_actions:
            env["GITHUB_ACTIONS"] = "true"
        result = subprocess.run(
            [str(SCRIPT), *args],
            cwd=self.root / "backend",  # the script must find the repo root itself
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return Run(result.returncode, result.stdout + result.stderr, calls)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def scratch_repo(tmp_path: Path) -> ScratchRepo:
    """A git repo with two committed locks, one nested, and one untracked."""
    root = tmp_path / "repo"
    for project in ("backend", "integration_workers/google", "untracked"):
        (root / project).mkdir(parents=True)
        (root / project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "backend/uv.lock", "integration_workers/google/uv.lock")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(FAKE_UV, encoding="utf-8")
    fake_uv.chmod(0o755)
    return ScratchRepo(root=root, bin_dir=bin_dir)


class TestRelockScript:
    def test_is_executable(self) -> None:
        assert SCRIPT.is_file(), f"missing {SCRIPT}"
        assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"

    def test_relocks_every_tracked_lock_and_nothing_else(
        self, scratch_repo: ScratchRepo
    ) -> None:
        run = scratch_repo.run()

        assert run.returncode == 0, run.output
        assert run.uv_calls == [
            "backend lock --quiet --directory backend",
            "integration_workers/google lock --quiet --directory "
            "integration_workers/google",
        ]

    def test_check_mode_only_checks(self, scratch_repo: ScratchRepo) -> None:
        run = scratch_repo.run("--check")

        assert run.returncode == 0, run.output
        assert [call.split()[1:3] for call in run.uv_calls] == [
            ["lock", "--check"],
            ["lock", "--check"],
        ]

    def test_never_upgrades(self, scratch_repo: ScratchRepo) -> None:
        # A relock must change only what the new metadata forces.
        run = scratch_repo.run()

        assert run.uv_calls
        assert not [call for call in run.uv_calls if "--upgrade" in call]

    def test_a_failing_project_is_named_and_the_rest_still_run(
        self, scratch_repo: ScratchRepo
    ) -> None:
        run = scratch_repo.run(fail="backend")

        assert run.returncode == 1
        assert len(run.uv_calls) == 2, "the other project must still be relocked"
        assert "error: backend could not be relocked" in run.output
        assert "integration_workers/google could not" not in run.output

    def test_a_stale_lock_is_reported_as_a_github_annotation(
        self, scratch_repo: ScratchRepo
    ) -> None:
        run = scratch_repo.run(
            "--check", fail="integration_workers/google", github_actions=True
        )

        assert run.returncode == 1
        assert (
            "::error file=integration_workers/google/uv.lock::"
            "integration_workers/google/uv.lock is stale"
        ) in run.output

    def test_rejects_unknown_arguments(self, scratch_repo: ScratchRepo) -> None:
        run = scratch_repo.run("--upgrade")

        assert run.returncode == 2
        assert "usage:" in run.output
        assert run.uv_calls == []

    def test_fails_when_no_lock_is_committed(self, scratch_repo: ScratchRepo) -> None:
        _git(scratch_repo.root, "rm", "-q", "--cached", "-r", ".")

        run = scratch_repo.run()

        assert run.returncode == 1
        assert "no committed uv.lock files" in run.output
        assert run.uv_calls == []


def test_python_locks_job_runs_the_script_check() -> None:
    body = _block(_read(CI_WORKFLOW), "python-locks:")
    assert "needs: changes" in body, "python-locks must sit behind the stack gate"
    assert "scripts/relock-python.sh --check" in body


def test_pre_commit_relocks_on_manifest_or_lock_changes() -> None:
    hook = _block(_read(PRE_COMMIT), "- id: uv-lock-python")
    assert "entry: scripts/relock-python.sh" in hook
    assert "language: system" in hook
    assert "pass_filenames: false" in hook
    files = re.search(r"files: (?P<pattern>.+)", hook)
    assert files, "uv-lock-python needs a files pattern"
    pattern = re.compile(files["pattern"].strip().strip("'\""))
    for path in (
        "core_shared/pyproject.toml",
        "integration_workers/google/uv.lock",
        "backend/pyproject.toml",
    ):
        assert pattern.search(path), f"hook must run when {path} is staged"
    assert not pattern.search("backend/app/main.py")


class TestRelockDependentsWorkflow:
    def test_never_uses_pull_request_target(self) -> None:
        assert "pull_request_target" not in _read(WORKFLOW)

    def test_triggers_only_on_core_shared_manifest_prs_to_main(self) -> None:
        on = _block(_read(WORKFLOW), "on:")
        assert re.fullmatch(
            r"\s*pull_request:\s*branches: \[main\]\s*"
            r"paths:\s*- ['\"]?core_shared/pyproject\.toml['\"]?\s*",
            on,
        ), f"unexpected trigger:\n{on}"

    def test_job_runs_only_for_dependabots_own_same_repo_prs(self) -> None:
        content = _read(WORKFLOW)
        conditions = re.findall(
            r"^    if: (?:>-?|\|)?\n((?:      .*\n)+)", content, re.MULTILINE
        )
        assert len(conditions) == 1, "expected exactly one job, gated by `if:`"
        gate = " ".join(conditions[0].split())
        for required in (
            "github.actor == 'dependabot[bot]'",
            "github.event.pull_request.user.login == 'dependabot[bot]'",
            "github.event.pull_request.head.repo.full_name == github.repository",
        ):
            assert required in gate, f"job gate is missing `{required}`"
        assert " || " not in gate, "every gate condition must hold (no `||`)"

    def test_references_only_the_relock_app_secrets(self) -> None:
        secrets = set(re.findall(r"secrets\.([A-Z_]+)", _read(WORKFLOW)))
        assert secrets == {"RELOCK_APP_ID", "RELOCK_APP_PRIVATE_KEY"}, secrets

    def test_pushes_with_an_app_token_so_ci_reruns(self) -> None:
        # A push made with GITHUB_TOKEN does not trigger workflows, so the
        # relocked head would never get CI.
        content = _read(WORKFLOW)
        assert "actions/create-github-app-token@" in content
        assert "token: ${{ steps.app-token.outputs.token }}" in content

    def test_runs_the_relock_script(self) -> None:
        assert "scripts/relock-python.sh" in _read(WORKFLOW)

    def test_default_token_is_read_only(self) -> None:
        assert re.search(
            r"^permissions:\n  contents: read\n", _read(WORKFLOW), re.MULTILINE
        )
