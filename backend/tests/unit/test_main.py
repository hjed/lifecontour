"""Unit tests for app startup helpers."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.infrastructure.config import Settings
from app.main import UVICORN_TIMEOUT_KEEP_ALIVE_SECONDS, run_app

REPO_ROOT = Path(__file__).resolve().parents[3]
UVICORN_LAUNCH_SCRIPTS = (
    REPO_ROOT / "docker" / "backend" / "start.sh",
    REPO_ROOT / "docker" / "backend" / "start-dev.sh",
    REPO_ROOT / "scripts" / "dev.sh",
)


def test_settings_host_default_is_loopback() -> None:
    """Direct local startup should default to loopback, not all interfaces."""
    assert Settings.model_fields["host"].default == "127.0.0.1"


@patch("uvicorn.run")
def test_run_app_uses_settings_host_and_port(mock_run) -> None:
    """run_app should delegate bind settings from Settings."""
    settings = Settings(host="127.0.0.1", port=8123, log_level="DEBUG", debug=False)

    run_app(settings)

    mock_run.assert_called_once_with(
        "app.main:app",
        host="127.0.0.1",
        port=8123,
        reload=False,
        log_level="debug",
        timeout_keep_alive=UVICORN_TIMEOUT_KEEP_ALIVE_SECONDS,
    )


@pytest.mark.parametrize("script", UVICORN_LAUNCH_SCRIPTS, ids=lambda p: p.name)
def test_launch_script_sets_keep_alive_timeout(script: Path) -> None:
    """Every uvicorn launch must use the same keep-alive timeout as run_app.

    A launch without the flag falls back to uvicorn's 5 s default, the window
    in which the Next.js proxy reuses sockets uvicorn is closing (#1862).
    """
    match = re.search(r"--timeout-keep-alive\s+(\d+)", script.read_text())

    assert match is not None, f"{script.name} does not set --timeout-keep-alive"
    assert int(match.group(1)) == UVICORN_TIMEOUT_KEEP_ALIVE_SECONDS
