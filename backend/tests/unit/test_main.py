"""Unit tests for app startup helpers."""

from unittest.mock import patch

from app.infrastructure.config import Settings
from app.main import run_app


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
    )
