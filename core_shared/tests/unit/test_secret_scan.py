"""Unit tests for ``scripts/secret_scan.py`` and the gitleaks guardrail config.

The CI ``secret-scan`` job runs the script, which picks the commit range to
scan from the GitHub event and hands it to gitleaks. The range rules are the
part that fails silently (a wrong range scans nothing and passes), so they are
tested here with an injected fake command runner; no git or gitleaks binary is
involved.

Like ``test_teardown_workspace.py`` this reaches out of ``core_shared`` to
repo-root files; the script is loaded by path because ``scripts/`` is not an
importable package.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

# core_shared/tests/unit/<this file> -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "secret_scan.py"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "scripts").is_dir(),
    reason="scripts/ not present (isolated core_shared checkout)",
)

BASE = "a" * 40
HEAD = "b" * 40
BEFORE = "c" * 40
AFTER = "d" * 40
ZERO = "0" * 40
AUDITED_VERSION = (8, 30, 1)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("secret_scan", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: 3.14 resolves the dataclass annotations through
    # sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


@dataclass
class FakeRunner:
    """Records every argv; ``missing`` commits fail ``git cat-file -e``."""

    missing: set[str] = field(default_factory=set)
    gitleaks_exit: int = 0
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))
        if argv[:3] == ["git", "cat-file", "-e"]:
            sha = argv[3].removesuffix("^{commit}")
            return 1 if sha in self.missing else 0
        return self.gitleaks_exit

    @property
    def gitleaks_calls(self) -> list[list[str]]:
        return [call for call in self.calls if call[0] != "git"]


def _resolve(script: ModuleType, event: str, payload: dict[str, object]) -> str:
    return _resolve_with(script, event, payload, FakeRunner())


def _resolve_with(
    script: ModuleType,
    event: str,
    payload: dict[str, object],
    runner: FakeRunner,
) -> str:
    target = script.target_from_event(event, payload)
    log_opts: str = script.resolve_log_opts(target, runner)
    return log_opts


def _pr_payload() -> dict[str, object]:
    return {"pull_request": {"base": {"sha": BASE}, "head": {"sha": HEAD}}}


def _push_payload(before: str = BEFORE) -> dict[str, object]:
    return {"before": before, "after": AFTER}


@pytest.mark.unit
class TestResolveLogOpts:
    """Each GitHub event maps to the commit range the iteration doc specifies."""

    def test_pull_request_scans_base_to_head(self, script: ModuleType) -> None:
        assert _resolve(script, "pull_request", _pr_payload()) == f"{BASE}..{HEAD}"

    def test_push_scans_before_to_after(self, script: ModuleType) -> None:
        assert _resolve(script, "push", _push_payload()) == f"{BEFORE}..{AFTER}"

    def test_push_with_zero_before_scans_full_history_of_after(
        self, script: ModuleType
    ) -> None:
        # A new branch or a tag push (release.yml -> workflow_call) has no
        # previous commit.
        assert _resolve(script, "push", _push_payload(ZERO)) == AFTER

    def test_force_push_with_unreachable_before_scans_full_history(
        self, script: ModuleType
    ) -> None:
        runner = FakeRunner(missing={BEFORE})
        assert _resolve_with(script, "push", _push_payload(), runner) == AFTER

    @pytest.mark.parametrize("event", ["workflow_dispatch", "workflow_call"])
    def test_dispatch_and_call_scan_full_history_of_head(
        self, script: ModuleType, event: str
    ) -> None:
        assert _resolve(script, event, {}) == "HEAD"

    def test_unknown_event_fails_safe_to_full_history(self, script: ModuleType) -> None:
        assert _resolve(script, "schedule", {}) == "HEAD"


@pytest.mark.unit
class TestBuildCommand:
    def test_command_uses_committed_config_and_redacts(
        self, script: ModuleType
    ) -> None:
        argv: list[str] = script.build_command(f"{BASE}..{HEAD}", "gitleaks")
        assert argv[:2] == ["gitleaks", "git"]
        assert f"--log-opts={BASE}..{HEAD}" in argv
        assert argv[argv.index("--config") + 1] == ".gitleaks.toml"
        assert argv[argv.index("--gitleaks-ignore-path") + 1] == ".gitleaksignore"
        assert "--redact" in argv
        assert argv[argv.index("--exit-code") + 1] == "1"


@pytest.mark.unit
class TestMain:
    def test_main_without_event_scans_full_history(self, script: ModuleType) -> None:
        runner = FakeRunner()
        script.main({"GITLEAKS_BIN": "/opt/gitleaks"}, runner)
        [call] = runner.gitleaks_calls
        assert call[0] == "/opt/gitleaks"
        assert "--log-opts=HEAD" in call

    def test_main_returns_the_gitleaks_exit_code(self, script: ModuleType) -> None:
        assert script.main({}, FakeRunner(gitleaks_exit=1)) == 1


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


@pytest.mark.unit
class TestGuardrailConfig:
    """The hook and the CI job run the audited gitleaks version and config."""

    def test_pre_commit_and_ci_pin_the_same_gitleaks_version(self) -> None:
        pre_commit = (REPO_ROOT / ".pre-commit-config.yaml").read_text("utf-8")
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
        hook = re.search(
            r"repo: https://github\.com/gitleaks/gitleaks\s+rev: v(\S+)", pre_commit
        )
        job = re.search(r'GITLEAKS_VERSION: "(\S+)"', ci)
        assert hook is not None, "gitleaks hook missing from .pre-commit-config.yaml"
        assert job is not None, "GITLEAKS_VERSION missing from ci.yml"
        assert hook.group(1) == job.group(1)
        assert _version(job.group(1)) >= AUDITED_VERSION

    def test_every_allowlist_entry_targets_rules(self) -> None:
        # A global allowlist's `paths` skip whole files in gitleaks 8.30,
        # whatever `condition` says; see the note at the top of .gitleaks.toml.
        config = tomllib.loads((REPO_ROOT / ".gitleaks.toml").read_text("utf-8"))
        allowlists = config.get("allowlists", [])
        assert allowlists
        for entry in allowlists:
            assert entry.get("targetRules"), entry.get("description")
