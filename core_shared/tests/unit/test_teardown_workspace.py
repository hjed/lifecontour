"""Unit tests for ``scripts/teardown_workspace.py``.

The teardown script removes every Docker resource belonging to one worktree's
compose project (``pms_test_<N>``), and must keep working when the worktree
itself has already been deleted. These tests exercise it with an injected fake
command runner, so no Docker daemon is involved.

Like ``test_worker_tooling_standardisation.py`` this reaches out of
``core_shared`` to a repo-root file; the script is loaded by path because
``scripts/`` is not an importable package.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# core_shared/tests/unit/<this file> -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "teardown_workspace.py"
WORKSPACE_ENV_PATH = REPO_ROOT / "scripts" / "workspace_env.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT_PATH.is_file(),
    reason="scripts/ not present (isolated core_shared checkout)",
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("teardown_workspace", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the script's dataclasses use PEP 563 annotations,
    # which 3.14 resolves by looking the module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


# ---------------------------------------------------------------------------
# Fake runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeResult:
    """Duck-typed stand-in for the script's ``CommandResult``."""

    argv: list[str]
    returncode: int
    stdout: str


@dataclass
class FakeRunner:
    """Records every argv and replays canned stdout for read-only queries.

    ``responses`` maps a substring-matched argv (joined with spaces) to stdout.
    Anything unmatched returns empty stdout and exit 0.
    """

    responses: dict[str, str] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    raises: dict[str, BaseException] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str]) -> Any:
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for needle, exc in self.raises.items():
            if needle in joined:
                raise exc
        stdout = ""
        for needle, out in self.responses.items():
            if needle in joined:
                stdout = out
                break
        returncode = 0
        for needle, code in self.failures.items():
            if needle in joined:
                returncode = code
                break
        return FakeResult(argv=list(argv), returncode=returncode, stdout=stdout)

    @property
    def joined_calls(self) -> list[str]:
        return [" ".join(call) for call in self.calls]

    def calls_matching(self, needle: str) -> list[str]:
        return [call for call in self.joined_calls if needle in call]


MUTATING_FRAGMENTS = (
    " rm ",
    " down",
    " kill ",
    " stop ",
    " prune",
)


def _mutating_calls(runner: FakeRunner) -> list[str]:
    return [
        call
        for call in runner.joined_calls
        if any(fragment in f"{call} " for fragment in MUTATING_FRAGMENTS)
    ]


# ---------------------------------------------------------------------------
# Prefix derivation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDerivePrefix:
    """The script must reproduce ``scripts/workspace_env.py`` exactly."""

    def test_matches_workspace_env_for_repo_root(self, script: ModuleType) -> None:
        expected = json.loads(
            subprocess.run(
                [sys.executable, str(WORKSPACE_ENV_PATH), "json"],
                check=True,
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            ).stdout
        )["CONTAINER_PREFIX"]

        assert script.derive_prefix(REPO_ROOT) == expected

    def test_matches_workspace_env_for_another_workspace(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        """Cross-check against a real copy of workspace_env.py in a fake worktree."""
        fake_scripts = tmp_path / "scripts"
        fake_scripts.mkdir()
        shutil.copy(WORKSPACE_ENV_PATH, fake_scripts / "workspace_env.py")

        expected = subprocess.run(
            [
                sys.executable,
                str(fake_scripts / "workspace_env.py"),
                "CONTAINER_PREFIX",
            ],
            check=True,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
        ).stdout.strip()

        assert script.derive_prefix(tmp_path) == expected

    def test_prefix_shape_and_range(self, script: ModuleType) -> None:
        prefix = script.derive_prefix("/some/worktree/path")
        assert prefix.startswith("pms_test_")
        offset = int(prefix.removeprefix("pms_test_"))
        assert 1 <= offset <= 99

    def test_ci_collapses_to_unprefixed_project(self, script: ModuleType) -> None:
        assert script.derive_prefix("/some/worktree/path", ci=True) == "pms"

    def test_deleted_workspace_path_still_resolves(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        """A worktree removed before teardown runs must still hash identically."""
        gone = tmp_path / "worktrees" / "LOCAL-1" / "checkout"
        gone.mkdir(parents=True)
        before = script.derive_prefix(gone)
        shutil.rmtree(tmp_path / "worktrees")

        assert script.derive_prefix(gone) == before

    def test_relative_path_is_resolved_against_cwd(
        self, script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "child").mkdir()
        monkeypatch.chdir(tmp_path)

        assert script.derive_prefix("child") == script.derive_prefix(tmp_path / "child")

    def test_trailing_slash_does_not_change_prefix(self, script: ModuleType) -> None:
        assert script.derive_prefix("/a/b/") == script.derive_prefix("/a/b")


@pytest.mark.unit
class TestIsCi:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
    def test_truthy_values(self, script: ModuleType, value: str) -> None:
        assert script.is_ci({"CI": value}) is True
        assert script.is_ci({"GITHUB_ACTIONS": value}) is True

    @pytest.mark.parametrize("value", ["", "false", "0", "no"])
    def test_falsey_values(self, script: ModuleType, value: str) -> None:
        assert script.is_ci({"CI": value}) is False

    def test_missing_is_false(self, script: ModuleType) -> None:
        assert script.is_ci({}) is False


# ---------------------------------------------------------------------------
# Safety guard: never nuke the shared local dev/prod stack
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnprefixedProjectGuard:
    def test_bare_pms_refused_by_default(self, script: ModuleType) -> None:
        with pytest.raises(script.UnsafeTeardownError):
            script.check_prefix_is_safe("pms", ci=False, force=False)

    def test_bare_pms_allowed_in_ci(self, script: ModuleType) -> None:
        script.check_prefix_is_safe("pms", ci=True, force=False)

    def test_bare_pms_allowed_with_force(self, script: ModuleType) -> None:
        script.check_prefix_is_safe("pms", ci=False, force=True)

    def test_workspace_prefix_always_allowed(self, script: ModuleType) -> None:
        script.check_prefix_is_safe("pms_test_41", ci=False, force=False)

    def test_empty_prefix_refused(self, script: ModuleType) -> None:
        with pytest.raises(script.UnsafeTeardownError):
            script.check_prefix_is_safe("", ci=True, force=True)


# ---------------------------------------------------------------------------
# Compose command construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComposeDownCommand:
    def test_includes_project_file_profiles_and_volumes(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        compose = tmp_path / "docker-compose.yml"
        env_file = tmp_path / ".env.test"
        argv = script.build_compose_down_command(
            "pms_test_41", compose, env_file, remove_volumes=True
        )

        assert argv[:2] == ["docker", "compose"]
        assert "-p" in argv and argv[argv.index("-p") + 1] == "pms_test_41"
        assert "-f" in argv and argv[argv.index("-f") + 1] == str(compose)
        assert argv[argv.index("--env-file") + 1] == str(env_file)
        for profile in ("dev", "test", "test-backend", "prod"):
            assert profile in argv, f"missing --profile {profile}"
        assert argv.index("down") > argv.index("--profile")
        assert "--volumes" in argv
        assert "--remove-orphans" in argv

    def test_keep_volumes_drops_the_volumes_flag(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        argv = script.build_compose_down_command(
            "pms_test_41",
            tmp_path / "docker-compose.yml",
            None,
            remove_volumes=False,
        )

        assert "--volumes" not in argv
        assert "--env-file" not in argv


@pytest.mark.unit
class TestComposeFileResolution:
    def test_prefers_the_target_workspace_compose_file(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        workspace = tmp_path / "worktree"
        workspace.mkdir()
        (workspace / "docker-compose.yml").write_text("services: {}\n")

        assert script.resolve_compose_file(workspace, REPO_ROOT) == (
            workspace / "docker-compose.yml"
        )

    def test_falls_back_to_the_scripts_own_repo(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        """The worktree is gone, but its compose project is identical to ours."""
        assert script.resolve_compose_file(tmp_path / "deleted", REPO_ROOT) == (
            REPO_ROOT / "docker-compose.yml"
        )

    def test_returns_none_when_no_compose_file_is_reachable(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        assert script.resolve_compose_file(tmp_path / "gone", tmp_path / "also") is None

    def test_env_file_is_optional(self, script: ModuleType, tmp_path: Path) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services: {}\n")
        assert script.resolve_env_file(compose) is None

        (tmp_path / ".env.test").write_text("FOO=bar\n")
        assert script.resolve_env_file(compose) == tmp_path / ".env.test"


# ---------------------------------------------------------------------------
# Teardown orchestration
# ---------------------------------------------------------------------------


def _teardown(
    script: ModuleType,
    runner: FakeRunner,
    *,
    prefix: str = "pms_test_41",
    compose_file: Path | None = None,
    **kwargs: Any,
) -> Any:
    return script.WorkspaceTeardown(
        prefix=prefix,
        compose_file=compose_file,
        env_file=None,
        runner=runner,
        log=lambda _msg: None,
        **kwargs,
    )


@pytest.mark.unit
class TestSweep:
    def test_removes_containers_found_by_project_label(
        self, script: ModuleType
    ) -> None:
        runner = FakeRunner(
            responses={
                "label=com.docker.compose.project=pms_test_41": "abc123\ndef456\n"
            }
        )
        summary = _teardown(script, runner).run()

        assert summary.containers_removed == ["abc123", "def456"]
        removals = runner.calls_matching("docker rm")
        assert removals, "expected containers to be force-removed"
        assert "abc123" in removals[0] and "def456" in removals[0]

    def test_removes_containers_found_only_by_name(self, script: ModuleType) -> None:
        """Compose sets explicit container_name, so name is a second safety net."""
        runner = FakeRunner(responses={"name=^pms_test_41-": "orphan1\n"})
        summary = _teardown(script, runner).run()

        assert "orphan1" in summary.containers_removed

    def test_container_ids_are_deduplicated(self, script: ModuleType) -> None:
        runner = FakeRunner(
            responses={
                "label=com.docker.compose.project=pms_test_41": "abc123\n",
                "name=^pms_test_41-": "abc123\n",
            }
        )
        summary = _teardown(script, runner).run()

        assert summary.containers_removed == ["abc123"]

    def test_name_filter_is_anchored_so_sibling_workspaces_are_untouched(
        self, script: ModuleType
    ) -> None:
        runner = FakeRunner()
        _teardown(script, runner, prefix="pms_test_4").run()

        name_filters = runner.calls_matching("name=^pms_test_4-")
        assert name_filters, "container name filter must anchor on '<prefix>-'"
        volume_filters = runner.calls_matching("name=^pms_test_4_")
        assert volume_filters, "volume name filter must anchor on '<prefix>_'"

    def test_removes_volumes_by_label_and_name(self, script: ModuleType) -> None:
        runner = FakeRunner(
            responses={
                "volume ls": "pms_test_41_postgres_data\npms_test_41_redis_data\n"
            }
        )
        summary = _teardown(script, runner).run()

        assert summary.volumes_removed == [
            "pms_test_41_postgres_data",
            "pms_test_41_redis_data",
        ]
        assert runner.calls_matching("docker volume rm")

    def test_shared_network_is_never_removed(self, script: ModuleType) -> None:
        """personal-management has a fixed name and is shared by every worktree."""
        runner = FakeRunner(
            responses={"network ls": "personal-management\npms_test_41_default\n"}
        )
        summary = _teardown(script, runner).run()

        assert summary.networks_removed == ["pms_test_41_default"]
        for call in runner.calls_matching("docker network rm"):
            assert "personal-management" not in call

    def test_no_removal_commands_when_nothing_is_found(
        self, script: ModuleType
    ) -> None:
        runner = FakeRunner()
        summary = _teardown(script, runner).run()

        assert summary.containers_removed == []
        assert not runner.calls_matching("docker rm")
        assert not runner.calls_matching("docker volume rm")
        assert not runner.calls_matching("docker network rm")

    def test_dry_run_issues_no_mutating_commands(self, script: ModuleType) -> None:
        runner = FakeRunner(
            responses={
                "label=com.docker.compose.project=pms_test_41": "abc123\n",
                "volume ls": "pms_test_41_postgres_data\n",
                "network ls": "pms_test_41_default\n",
            }
        )
        summary = _teardown(script, runner, dry_run=True).run()

        assert _mutating_calls(runner) == []
        assert summary.containers_removed == ["abc123"]

    def test_dry_run_skips_compose_down(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services: {}\n")
        runner = FakeRunner()

        _teardown(script, runner, compose_file=compose, dry_run=True).run()

        assert not runner.calls_matching("docker compose ")


@pytest.mark.unit
class TestComposeDownIntegrationWithSweep:
    def test_compose_down_runs_before_the_sweep(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services: {}\n")
        runner = FakeRunner()

        _teardown(script, runner, compose_file=compose).run()

        assert "down" in runner.joined_calls[0]
        assert any("ps -a" in call for call in runner.joined_calls[1:])

    def test_sweep_still_runs_without_a_compose_file(self, script: ModuleType) -> None:
        runner = FakeRunner(
            responses={"label=com.docker.compose.project=pms_test_41": "abc123\n"}
        )
        summary = _teardown(script, runner, compose_file=None).run()

        assert not runner.calls_matching("docker compose ")
        assert summary.containers_removed == ["abc123"]

    def test_failed_compose_down_does_not_abort_the_sweep(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services: {}\n")
        runner = FakeRunner(
            responses={"label=com.docker.compose.project=pms_test_41": "abc123\n"},
            failures={"down": 1},
        )

        summary = _teardown(script, runner, compose_file=compose).run()

        assert summary.containers_removed == ["abc123"]
        assert summary.errors, "a failed compose down should be reported"


@pytest.mark.unit
class TestBestEffortBehaviour:
    def test_missing_docker_binary_is_reported_not_raised(
        self, script: ModuleType
    ) -> None:
        runner = FakeRunner(raises={"docker": FileNotFoundError("docker")})
        summary = _teardown(script, runner).run()

        assert summary.errors
        assert summary.containers_removed == []

    def test_remaining_resources_are_reported(self, script: ModuleType) -> None:
        """Removal silently failing (e.g. a container held open) must surface."""
        runner = FakeRunner(
            responses={
                "label=com.docker.compose.project=pms_test_41": "stubborn\n",
            },
            failures={"docker rm": 1},
        )
        summary = _teardown(script, runner).run()

        assert summary.remaining
        assert summary.errors


# ---------------------------------------------------------------------------
# Stale project pruning
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindStaleProjects:
    def test_selects_only_projects_whose_workdir_is_gone(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        alive = tmp_path / "alive"
        alive.mkdir()
        runner = FakeRunner(
            responses={
                "ps -a": (
                    f"pms_test_10\t{alive}\n"
                    f"pms_test_20\t{tmp_path / 'deleted'}\n"
                    f"pms_test_20\t{tmp_path / 'deleted'}\n"
                )
            }
        )

        assert script.find_stale_projects(runner) == ["pms_test_20"]

    def test_ignores_non_workspace_projects(
        self, script: ModuleType, tmp_path: Path
    ) -> None:
        runner = FakeRunner(
            responses={
                "ps -a": (
                    f"pms\t{tmp_path / 'deleted'}\n"
                    f"some-other-project\t{tmp_path / 'deleted'}\n"
                )
            }
        )

        assert script.find_stale_projects(runner) == []

    def test_ignores_rows_without_a_working_dir_label(self, script: ModuleType) -> None:
        runner = FakeRunner(responses={"ps -a": "pms_test_30\t\n\n"})

        assert script.find_stale_projects(runner) == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCli:
    def test_prefix_flag_bypasses_path_hashing(self, script: ModuleType) -> None:
        args = script.parse_args(["--prefix", "pms_test_7", "--dry-run"])
        assert args.prefix == "pms_test_7"

    def test_workspace_argument_is_optional(self, script: ModuleType) -> None:
        assert script.parse_args([]).workspace is None

    def test_dry_run_exits_zero(
        self, script: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = FakeRunner()
        monkeypatch.setattr(script, "default_runner", runner)

        assert script.main(["--prefix", "pms_test_41", "--dry-run", "--quiet"]) == 0
        assert _mutating_calls(runner) == []

    def test_refusing_the_dev_stack_exits_nonzero(
        self, script: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = FakeRunner()
        monkeypatch.setattr(script, "default_runner", runner)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

        assert script.main(["--prefix", "pms", "--quiet"]) != 0
        assert runner.calls == []

    def test_best_effort_exit_zero_when_removal_fails(
        self, script: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = FakeRunner(
            responses={"label=com.docker.compose.project=pms_test_41": "stubborn\n"},
            failures={"docker rm": 1},
        )
        monkeypatch.setattr(script, "default_runner", runner)

        assert script.main(["--prefix", "pms_test_41", "--quiet"]) == 0

    def test_strict_exit_nonzero_when_removal_fails(
        self, script: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = FakeRunner(
            responses={"label=com.docker.compose.project=pms_test_41": "stubborn\n"},
            failures={"docker rm": 1},
        )
        monkeypatch.setattr(script, "default_runner", runner)

        assert script.main(["--prefix", "pms_test_41", "--quiet", "--strict"]) != 0

    def test_prune_stale_tears_down_each_stale_project(
        self, script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = FakeRunner(
            responses={"ps -a --format": f"pms_test_20\t{tmp_path / 'deleted'}\n"}
        )
        monkeypatch.setattr(script, "default_runner", runner)

        assert script.main(["--prune-stale", "--quiet"]) == 0
        assert runner.calls_matching("label=com.docker.compose.project=pms_test_20"), (
            "the stale project should have been swept"
        )
