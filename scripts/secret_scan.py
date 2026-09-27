#!/usr/bin/env python3
"""Scan the commits a GitHub Actions event introduces for secrets.

Run by the ``secret-scan`` job in ``.github/workflows/ci.yml`` from the repo
root, after a ``fetch-depth: 0`` checkout. It picks the commit range from the
event and runs gitleaks over it with the committed ``.gitleaks.toml`` and
``.gitleaksignore``:

- ``pull_request``: ``base.sha..head.sha``;
- ``push``: ``before..after``, or the full history of ``after`` when
  ``before`` is the zero SHA (a new branch or tag) or no longer exists (a
  force-push);
- anything else (``workflow_dispatch`` for upper stack layers,
  ``workflow_call`` from the release workflow): the full history of ``HEAD``.
  Unknown events scan more, never less.

Output is redacted: Actions logs are public, so a finding never prints its
value. The exit code is gitleaks' own, non-zero on a finding.

Stdlib only; tested by ``core_shared/tests/unit/test_secret_scan.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ZERO_SHA = "0" * 40
FULL_HISTORY = "HEAD"

# Runs an argv and returns its exit code; injected by the tests.
Runner = Callable[[list[str]], int]


def default_runner(argv: list[str]) -> int:
    # Output streams straight to the job log.
    return subprocess.run(argv, check=False).returncode


@dataclass(frozen=True)
class ScanTarget:
    """The commit SHAs a GitHub event carries, where it carries them."""

    event_name: str
    base: str | None = None
    head: str | None = None
    before: str | None = None
    after: str | None = None


def target_from_event(event_name: str, payload: Mapping[str, Any]) -> ScanTarget:
    pull_request = payload.get("pull_request") or {}
    return ScanTarget(
        event_name=event_name,
        base=(pull_request.get("base") or {}).get("sha"),
        head=(pull_request.get("head") or {}).get("sha"),
        before=payload.get("before"),
        after=payload.get("after"),
    )


def _commit_exists(sha: str, runner: Runner) -> bool:
    return runner(["git", "cat-file", "-e", f"{sha}^{{commit}}"]) == 0


def resolve_log_opts(target: ScanTarget, runner: Runner) -> str:
    """Return the ``git log`` revision range gitleaks should scan."""
    if target.event_name == "pull_request" and target.base and target.head:
        return f"{target.base}..{target.head}"
    if target.event_name == "push" and target.after:
        before = target.before
        if before and before != ZERO_SHA and _commit_exists(before, runner):
            return f"{before}..{target.after}"
        return target.after
    return FULL_HISTORY


def build_command(log_opts: str, gitleaks: str) -> list[str]:
    return [
        gitleaks,
        "git",
        f"--log-opts={log_opts}",
        "--config",
        ".gitleaks.toml",
        "--gitleaks-ignore-path",
        ".gitleaksignore",
        "--redact",
        "--no-banner",
        "--verbose",
        "--exit-code",
        "1",
    ]


def _load_payload(env: Mapping[str, str]) -> dict[str, Any]:
    event_path = env.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    payload: dict[str, Any] = json.loads(Path(event_path).read_text("utf-8"))
    return payload


def main(env: Mapping[str, str] = os.environ, runner: Runner = default_runner) -> int:
    target = target_from_event(env.get("GITHUB_EVENT_NAME", ""), _load_payload(env))
    log_opts = resolve_log_opts(target, runner)
    print(f"secret-scan: {target.event_name or 'local'} -> git log {log_opts}")
    return runner(build_command(log_opts, env.get("GITLEAKS_BIN", "gitleaks")))


if __name__ == "__main__":
    sys.exit(main())
