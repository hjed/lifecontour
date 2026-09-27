"""Integration tests: the real gitleaks binary with the committed config.

Each test builds a throwaway git repository seeded with the repo's own
``.gitleaks.toml`` and ``.gitleaksignore``, commits content into it, and runs
either ``scripts/secret_scan.py`` (what the CI ``secret-scan`` job runs) or the
pre-commit hook's exact gitleaks command. This is the iteration doc's
verification made repeatable: a fake AWS-style key is rejected, and the
allowlist does not hide real-looking keys in the files it covers.

Fake keys are generated at runtime so this repository never contains one.

Needs gitleaks on ``PATH`` or in ``GITLEAKS_BIN`` (the version pinned in
``ci.yml``); see docs/code-quality-standards.md. It runs in the CI
``secret-scan`` job, which installs it.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# core_shared/tests/integration/<this file> -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "secret_scan.py"

pytestmark = [pytest.mark.integration, pytest.mark.gitleaks]

# The hook's entry in gitleaks' .pre-commit-hooks.yaml (id: gitleaks).
PRE_COMMIT_ARGS = ["git", "--pre-commit", "--redact", "--staged", "--verbose"]

_BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def fake_aws_access_key() -> str:
    """An AWS-style access key ID that matches gitleaks' aws-access-token rule."""
    return "AKIA" + "".join(secrets.choice(_BASE32) for _ in range(16))


def fake_generic_secret() -> str:
    """A high-entropy value that is not one of the allowlisted placeholders."""
    return "".join(secrets.choice(_ALNUM) for _ in range(32))


@pytest.fixture(scope="module")
def gitleaks_bin() -> str:
    found = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
    if not found:
        pytest.fail(
            "gitleaks is not installed. Install the version pinned in "
            ".github/workflows/ci.yml (see docs/code-quality-standards.md) "
            "or set GITLEAKS_BIN."
        )
    return found


@dataclass(frozen=True)
class ScanResult:
    returncode: int
    output: str


class TempRepo:
    """A git repository in ``tmp_path`` carrying the committed gitleaks config."""

    def __init__(self, root: Path, gitleaks_bin: str) -> None:
        self.root = root
        self.gitleaks_bin = gitleaks_bin
        root.mkdir()
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "secret-scan test")
        self._git("config", "commit.gpgsign", "false")
        for name in (".gitleaks.toml", ".gitleaksignore"):
            shutil.copy(REPO_ROOT / name, root / name)
        self.commit("gitleaks config")

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def stage(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._git("add", path)

    def commit(self, message: str, files: dict[str, str] | None = None) -> str:
        for path, content in (files or {}).items():
            self.stage(path, content)
        self._git("add", "-A")
        self._git("commit", "-q", "--no-verify", "-m", message)
        return self._git("rev-parse", "HEAD")

    def _run(self, argv: list[str], env: dict[str, str]) -> ScanResult:
        completed = subprocess.run(
            argv,
            cwd=self.root,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=False,
        )
        return ScanResult(completed.returncode, completed.stdout + completed.stderr)

    def secret_scan(self, event: str, payload: dict[str, object]) -> ScanResult:
        """Run scripts/secret_scan.py as the CI job does."""
        event_path = self.root.parent / f"{self.root.name}-event.json"
        event_path.write_text(json.dumps(payload), encoding="utf-8")
        env = {
            "GITHUB_EVENT_NAME": event,
            "GITHUB_EVENT_PATH": str(event_path),
            "GITLEAKS_BIN": self.gitleaks_bin,
        }
        return self._run([sys.executable, str(SCRIPT_PATH)], env)

    def full_scan(self) -> ScanResult:
        return self.secret_scan("workflow_dispatch", {})

    def pre_commit_scan(self) -> ScanResult:
        return self._run([self.gitleaks_bin, *PRE_COMMIT_ARGS], {})


@pytest.fixture
def repo(tmp_path: Path, gitleaks_bin: str) -> TempRepo:
    return TempRepo(tmp_path / "repo", gitleaks_bin)


class TestSecretScanFlagsNewSecrets:
    def test_fake_aws_key_fails_the_scan_and_is_redacted(self, repo: TempRepo) -> None:
        key = fake_aws_access_key()
        repo.commit("add config", {"app/settings.py": f'AWS_KEY = "{key}"\n'})

        result = repo.full_scan()

        assert result.returncode == 1, result.output
        assert "aws-access-token" in result.output
        assert key not in result.output

    def test_aws_key_in_allowlisted_env_file_is_still_caught(
        self, repo: TempRepo
    ) -> None:
        repo.commit(
            "env",
            {".env.dev": f"AWS_ACCESS_KEY_ID={fake_aws_access_key()}\n"},
        )

        assert repo.full_scan().returncode == 1

    @pytest.mark.parametrize("path", [".env.dev", "backend/tests/conftest.py"])
    def test_non_placeholder_value_in_allowlisted_path_is_still_caught(
        self, repo: TempRepo, path: str
    ) -> None:
        # The allowlist pairs these paths with placeholder value regexes
        # (condition = "AND"), so a real-looking value is not hidden.
        repo.commit(
            "add secret", {path: f'client_secret = "{fake_generic_secret()}"\n'}
        )

        result = repo.full_scan()

        assert result.returncode == 1, result.output
        assert "generic-api-key" in result.output

    def test_dev_placeholders_in_env_file_pass(self, repo: TempRepo) -> None:
        repo.commit(
            "env placeholders",
            {
                ".env.dev": (
                    "GOOGLE_CLIENT_SECRET=dev-client-secret\n"
                    "MEILI_MASTER_KEY=dev_master_key_change_in_production\n"
                )
            },
        )

        result = repo.full_scan()

        assert result.returncode == 0, result.output


class TestSecretScanRange:
    def test_push_range_ignores_findings_before_it(self, repo: TempRepo) -> None:
        # The finding predates `before`, so a push scan of the new commit is
        # clean while a full-history scan (tag, dispatch) still reports it.
        before = repo.commit("old", {"old.py": f'KEY = "{fake_aws_access_key()}"\n'})
        after = repo.commit("new", {"new.py": "print('hello')\n"})

        push = repo.secret_scan("push", {"before": before, "after": after})

        assert push.returncode == 0, push.output
        assert repo.full_scan().returncode == 1

    def test_pull_request_range_flags_a_secret_in_the_pr(self, repo: TempRepo) -> None:
        base = repo.commit("base", {"README.md": "hello\n"})
        head = repo.commit("pr", {"app.py": f'KEY = "{fake_aws_access_key()}"\n'})

        result = repo.secret_scan(
            "pull_request",
            {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}},
        )

        assert result.returncode == 1, result.output


class TestPreCommitHook:
    def test_staged_fake_aws_key_is_rejected(self, repo: TempRepo) -> None:
        key = fake_aws_access_key()
        repo.stage("app/settings.py", f'AWS_KEY = "{key}"\n')

        result = repo.pre_commit_scan()

        assert result.returncode == 1, result.output
        assert key not in result.output

    def test_clean_staged_change_passes(self, repo: TempRepo) -> None:
        repo.stage("app/main.py", "print('hello')\n")

        assert repo.pre_commit_scan().returncode == 0
