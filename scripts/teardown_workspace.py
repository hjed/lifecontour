#!/usr/bin/env python3
"""Tear down the Docker compose stack belonging to one worktree.

Every worktree gets its own compose project name — ``pms_test_<N>``, derived by
``scripts/workspace_env.py`` from a hash of the worktree path — so several
checkouts can run the e2e/integration stacks side by side. When a worktree is
deleted, its containers, volumes and networks are left behind: they are keyed
to a directory that no longer exists.

This script removes everything belonging to one such project. It is designed to
run *from a worktree-cleanup hook*, which means it must work after the target
worktree has already been deleted — so it re-derives the prefix from the path
itself rather than importing the (possibly gone) ``workspace_env.py``, and it
falls back to label-based removal when the compose file is unreachable.

Usage::

    # tear down the worktree this script lives in
    python3 scripts/teardown_workspace.py

    # tear down a worktree that is being (or has been) removed
    python3 /path/to/main/PMS/scripts/teardown_workspace.py /path/to/worktree

    # tear down by compose project name, when the path is unknown
    python3 scripts/teardown_workspace.py --prefix pms_test_41

    # sweep every workspace project whose worktree no longer exists
    python3 scripts/teardown_workspace.py --prune-stale

Safety rules:

* The shared ``personal-management`` network is never removed — it is declared
  with a fixed ``name:`` in ``docker-compose.yml``, so every worktree shares it.
* The unprefixed ``pms`` project (the local dev/prod stack) is refused unless
  running in CI or ``--force`` is passed.
* Only resources labelled with the target project — or named ``<prefix>-*`` /
  ``<prefix>_*`` — are touched. Other worktrees are left alone.
* Failures are reported, not raised: the script exits 0 by default so it can
  never block worktree deletion. Use ``--strict`` to opt into a non-zero exit.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Kept in sync with scripts/workspace_env.py — see derive_prefix().
WORKSPACE_PROJECT_PATTERN = re.compile(r"^pms_test_\d+$")
UNPREFIXED_PROJECT = "pms"

# Declared with an explicit `name:` in docker-compose.yml, so it is shared by
# every worktree's project. Removing it would break other running workspaces.
SHARED_NETWORK = "personal-management"

PROJECT_LABEL = "com.docker.compose.project"
WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"

COMPOSE_PROFILES = ("dev", "test", "test-backend", "prod")
COMPOSE_FILE_NAME = "docker-compose.yml"
ENV_FILE_NAME = ".env.test"
COMPOSE_STOP_TIMEOUT = "15"

# scripts/<this file> -> the repo root of the checkout the script lives in.
SCRIPT_REPO_ROOT = Path(__file__).resolve().parent.parent


class UnsafeTeardownError(Exception):
    """Raised when the requested project must not be torn down."""


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str


Runner = Callable[[list[str]], CommandResult]


@dataclass
class Summary:
    """What a teardown found and removed.

    ``containers_removed``/``volumes_removed``/``networks_removed`` list the
    resources *identified for removal* — under ``--dry-run`` nothing is
    actually deleted, but they are still reported so the run is inspectable.
    ``remaining`` holds anything still present after removal.
    """

    prefix: str
    containers_removed: list[str] = field(default_factory=list)
    volumes_removed: list[str] = field(default_factory=list)
    networks_removed: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def removed_anything(self) -> bool:
        return bool(
            self.containers_removed or self.volumes_removed or self.networks_removed
        )

    @property
    def clean(self) -> bool:
        return not self.errors and not self.remaining


def default_runner(argv: list[str]) -> CommandResult:
    """Run a command, capturing stdout. Never raises on a non-zero exit."""
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    if completed.returncode != 0 and completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)
    return CommandResult(
        argv=list(argv),
        returncode=completed.returncode,
        stdout=completed.stdout,
    )


# ---------------------------------------------------------------------------
# Prefix derivation (mirrors scripts/workspace_env.py)
# ---------------------------------------------------------------------------


def is_ci(env: Mapping[str, str]) -> bool:
    """Match ``workspace_env.py``'s notion of "running in CI"."""
    truthy = ("true", "1", "yes")
    return (
        env.get("CI", "").lower() in truthy
        or env.get("GITHUB_ACTIONS", "").lower() in truthy
    )


def derive_prefix(workspace: str | Path, *, ci: bool = False) -> str:
    """Return the compose project name for ``workspace``.

    Deliberately a copy of ``scripts/workspace_env.py``'s derivation rather
    than a call into it: by the time a cleanup hook runs, the target worktree
    (and its copy of that script) may already be gone. The two must stay in
    sync — ``test_teardown_workspace.py`` cross-checks them against a real
    ``workspace_env.py`` run.
    """
    if ci:
        return UNPREFIXED_PROJECT
    resolved = str(Path(workspace).resolve())
    offset = (int(hashlib.sha1(resolved.encode()).hexdigest(), 16) % 99) + 1
    return f"pms_test_{offset}"


def check_prefix_is_safe(prefix: str, *, ci: bool, force: bool) -> None:
    """Refuse to tear down the shared local dev/prod stack by accident."""
    if not prefix.strip():
        raise UnsafeTeardownError("no compose project name resolved")
    if prefix == UNPREFIXED_PROJECT and not (ci or force):
        raise UnsafeTeardownError(
            f"refusing to tear down the unprefixed '{UNPREFIXED_PROJECT}' project — "
            "that is the local dev/prod stack, not a worktree. "
            "Pass --force if you really mean it."
        )


# ---------------------------------------------------------------------------
# Compose command construction
# ---------------------------------------------------------------------------


def resolve_compose_file(workspace: Path | None, script_root: Path) -> Path | None:
    """Find a compose file describing the target project.

    Prefers the target worktree's own file; falls back to the one beside this
    script (every worktree has the same compose file, and ``down`` is driven by
    the project name, not the file's contents). Returns ``None`` when neither
    is reachable — the label sweep alone still cleans up.
    """
    candidates = []
    if workspace is not None:
        candidates.append(workspace / COMPOSE_FILE_NAME)
    candidates.append(script_root / COMPOSE_FILE_NAME)
    return next((path for path in candidates if path.is_file()), None)


def resolve_env_file(compose_file: Path) -> Path | None:
    """Return the ``.env.test`` beside ``compose_file``, if it exists."""
    env_file = compose_file.parent / ENV_FILE_NAME
    return env_file if env_file.is_file() else None


def build_compose_down_command(
    prefix: str,
    compose_file: Path,
    env_file: Path | None,
    *,
    remove_volumes: bool,
) -> list[str]:
    """Build the ``docker compose down`` argv for one project.

    Every profile is listed explicitly: services outside the active profiles
    are otherwise skipped, and a worktree may have been left running under any
    of them.
    """
    argv = ["docker", "compose", "-p", prefix, "-f", str(compose_file)]
    if env_file is not None:
        argv += ["--env-file", str(env_file)]
    for profile in COMPOSE_PROFILES:
        argv += ["--profile", profile]
    argv += ["down", "--remove-orphans", "--timeout", COMPOSE_STOP_TIMEOUT]
    if remove_volumes:
        argv.append("--volumes")
    return argv


# ---------------------------------------------------------------------------
# Stale project discovery
# ---------------------------------------------------------------------------


def find_stale_projects(
    runner: Runner,
    *,
    exists: Callable[[Path], bool] = Path.exists,
) -> list[str]:
    """Return ``pms_test_*`` projects whose recorded working directory is gone.

    Compose stamps each container with the directory it was started from, so a
    worktree deleted without teardown is identifiable from Docker alone.
    Projects with no containers left (only volumes) carry no working-directory
    label and cannot be classified; tear those down with ``--prefix``.
    """
    argv = [
        "docker",
        "ps",
        "-a",
        "--format",
        f'{{{{.Label "{PROJECT_LABEL}"}}}}\t{{{{.Label "{WORKING_DIR_LABEL}"}}}}',
    ]
    result = runner(argv)
    stale: list[str] = []
    for line in result.stdout.splitlines():
        project, _, working_dir = line.partition("\t")
        project, working_dir = project.strip(), working_dir.strip()
        if not project or not working_dir:
            continue
        if not WORKSPACE_PROJECT_PATTERN.match(project):
            continue
        if project in stale or exists(Path(working_dir)):
            continue
        stale.append(project)
    return stale


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        stripped = value.strip()
        if stripped:
            seen.setdefault(stripped, None)
    return list(seen)


class WorkspaceTeardown:
    """Removes every Docker resource belonging to one compose project."""

    def __init__(
        self,
        *,
        prefix: str,
        compose_file: Path | None,
        env_file: Path | None,
        runner: Runner = default_runner,
        log: Callable[[str], None] = print,
        dry_run: bool = False,
        remove_volumes: bool = True,
    ) -> None:
        self.prefix = prefix
        self.compose_file = compose_file
        self.env_file = env_file
        self.runner = runner
        self.log = log
        self.dry_run = dry_run
        self.remove_volumes = remove_volumes
        self.summary = Summary(prefix=prefix)
        self.compose_down_ran = False

    # -- command plumbing ---------------------------------------------------

    def _run(self, argv: list[str]) -> CommandResult | None:
        """Run a command, recording (never raising) any failure."""
        try:
            result = self.runner(argv)
        except OSError as exc:  # docker missing, not executable, ...
            self.summary.errors.append(f"{' '.join(argv)}: {exc}")
            return None
        if result.returncode != 0:
            self.summary.errors.append(
                f"exit {result.returncode}: {' '.join(argv)}".strip()
            )
        return result

    def _query(self, argv: list[str]) -> list[str]:
        result = self._run(argv)
        return _dedupe(result.stdout.splitlines()) if result is not None else []

    def _remove(self, argv: list[str], names: Sequence[str]) -> None:
        if not names:
            return
        if self.dry_run:
            self.log(f"  would run: {' '.join([*argv, *names])}")
            return
        self._run([*argv, *names])

    # -- discovery ----------------------------------------------------------

    def find_containers(self) -> list[str]:
        """Containers of this project, by label and by ``<prefix>-*`` name.

        The name filter is the safety net for the explicit ``container_name:``
        entries in the compose file, which can survive a partial run under a
        different project name. It is anchored so ``pms_test_4`` never matches
        ``pms_test_41-postgres``.
        """
        by_label = self._query(
            ["docker", "ps", "-aq", "--filter", f"label={PROJECT_LABEL}={self.prefix}"]
        )
        by_name = self._query(
            ["docker", "ps", "-aq", "--filter", f"name=^{self.prefix}-"]
        )
        return _dedupe([*by_label, *by_name])

    def find_volumes(self) -> list[str]:
        by_label = self._query(
            [
                "docker",
                "volume",
                "ls",
                "-q",
                "--filter",
                f"label={PROJECT_LABEL}={self.prefix}",
            ]
        )
        by_name = self._query(
            ["docker", "volume", "ls", "-q", "--filter", f"name=^{self.prefix}_"]
        )
        return _dedupe([*by_label, *by_name])

    def find_networks(self) -> list[str]:
        by_label = self._query(
            [
                "docker",
                "network",
                "ls",
                "--format",
                "{{.Name}}",
                "--filter",
                f"label={PROJECT_LABEL}={self.prefix}",
            ]
        )
        by_name = self._query(
            [
                "docker",
                "network",
                "ls",
                "--format",
                "{{.Name}}",
                "--filter",
                f"name=^{self.prefix}_",
            ]
        )
        return [
            name for name in _dedupe([*by_label, *by_name]) if name != SHARED_NETWORK
        ]

    # -- phases -------------------------------------------------------------

    def compose_down(self) -> None:
        if self.compose_file is None:
            self.log("  no compose file reachable — falling back to label sweep")
            return
        argv = build_compose_down_command(
            self.prefix,
            self.compose_file,
            self.env_file,
            remove_volumes=self.remove_volumes,
        )
        if self.dry_run:
            self.log(f"  would run: {' '.join(argv)}")
            return
        self._run(argv)
        self.compose_down_ran = True

    def sweep(self) -> None:
        containers = self.find_containers()
        self.summary.containers_removed = containers
        self._remove(["docker", "rm", "-f", "-v"], containers)

        volumes = self.find_volumes() if self.remove_volumes else []
        self.summary.volumes_removed = volumes
        self._remove(["docker", "volume", "rm", "-f"], volumes)

        networks = self.find_networks()
        self.summary.networks_removed = networks
        self._remove(["docker", "network", "rm"], networks)

    def verify(self) -> None:
        remaining = [*self.find_containers(), *self.find_volumes()]
        self.summary.remaining = remaining
        if remaining:
            self.summary.errors.append(
                f"{len(remaining)} resource(s) still present for {self.prefix}: "
                + ", ".join(remaining)
            )

    def run(self) -> Summary:
        self.log(f"Tearing down compose project '{self.prefix}'")
        self.compose_down()
        self.sweep()
        if not self.dry_run:
            self.verify()
        self._report()
        return self.summary

    def _report(self) -> None:
        summary = self.summary
        # `compose down` removes the bulk of a healthy project, so the sweep
        # counts are leftovers, not the whole teardown. Say which is which.
        scope = (
            "left behind by compose down"
            if self.compose_down_ran
            else "found for this project"
        )
        verb = "would remove" if self.dry_run else "removed"
        self.log(
            f"  {verb} {len(summary.containers_removed)} container(s), "
            f"{len(summary.volumes_removed)} volume(s), "
            f"{len(summary.networks_removed)} network(s) {scope}"
        )
        for error in summary.errors:
            self.log(f"  ! {error}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="teardown_workspace.py",
        description=(
            "Tear down the Docker compose stack for one worktree "
            "(its per-worktree pms_test_<N> project)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The worktree may already be deleted: its project name is derived "
            "from the path, and removal falls back to Docker labels."
        ),
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="worktree to tear down (default: the checkout this script lives in)",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="target a compose project directly, skipping path derivation",
    )
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="tear down every pms_test_* project whose worktree no longer exists",
    )
    parser.add_argument(
        "--keep-volumes",
        action="store_true",
        help="stop and remove containers but keep the project's volumes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be removed without changing anything",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"allow tearing down the unprefixed '{UNPREFIXED_PROJECT}' dev stack",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if anything failed or was left behind",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    return parser.parse_args(argv)


def _teardown_project(
    prefix: str,
    *,
    workspace: Path | None,
    args: argparse.Namespace,
    log: Callable[[str], None],
) -> Summary:
    compose_file = resolve_compose_file(workspace, SCRIPT_REPO_ROOT)
    return WorkspaceTeardown(
        prefix=prefix,
        compose_file=compose_file,
        env_file=resolve_env_file(compose_file) if compose_file else None,
        runner=default_runner,
        log=log,
        dry_run=args.dry_run,
        remove_volumes=not args.keep_volumes,
    ).run()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    log: Callable[[str], None] = (lambda _msg: None) if args.quiet else print
    ci = is_ci(os.environ)

    summaries: list[Summary] = []

    if args.prune_stale:
        stale = find_stale_projects(default_runner)
        if not stale:
            log("No stale workspace projects found.")
        for prefix in stale:
            summaries.append(
                _teardown_project(prefix, workspace=None, args=args, log=log)
            )
    else:
        workspace = Path(args.workspace) if args.workspace else SCRIPT_REPO_ROOT
        prefix = args.prefix or derive_prefix(workspace, ci=ci)
        try:
            check_prefix_is_safe(prefix, ci=ci, force=args.force)
        except UnsafeTeardownError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        summaries.append(
            _teardown_project(
                prefix,
                workspace=None if args.prefix and not args.workspace else workspace,
                args=args,
                log=log,
            )
        )

    if args.strict and not all(summary.clean for summary in summaries):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
