"""Unit tests for application settings (app.infrastructure.config)."""

import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings


class TestGeminiModels:
    """AI summary generation defaults to the latest stable Flash model."""

    def test_summary_model_defaults_to_latest_flash(self):
        settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

        assert settings.gemini_summary_model == "gemini-3.5-flash"


class TestCorsAllowOrigins:
    """The effective CORS allow-list must include the app's own public origin.

    MCP and OAuth discovery endpoints sit outside the same-origin Next.js
    ``/api`` proxy, so the deployed frontend calls them cross-origin. Deriving
    the origin from ``frontend_url`` / ``webhook_base_url`` guarantees the site
    is trusted even when ``CORS_ORIGINS`` wasn't explicitly updated.
    """

    def test_includes_frontend_and_webhook_origins(self):
        settings = Settings(
            cors_origins=["http://localhost:3000"],
            frontend_url="https://journal.hjed.net",
            webhook_base_url="https://journal.hjed.net",
        )

        origins = settings.cors_allow_origins

        assert "https://journal.hjed.net" in origins
        # Explicitly configured origins are preserved.
        assert "http://localhost:3000" in origins

    def test_strips_path_to_bare_origin(self):
        settings = Settings(
            cors_origins=[],
            frontend_url="https://app.example.com/some/path",
            webhook_base_url="",
        )

        assert settings.cors_allow_origins == ["https://app.example.com"]

    def test_deduplicates_origins(self):
        settings = Settings(
            cors_origins=["https://journal.hjed.net"],
            frontend_url="https://journal.hjed.net",
            webhook_base_url="https://journal.hjed.net/",
        )

        assert settings.cors_allow_origins.count("https://journal.hjed.net") == 1

    def test_ignores_empty_urls(self):
        settings = Settings(
            cors_origins=["http://localhost:3000"],
            frontend_url="",
            webhook_base_url="",
        )

        assert settings.cors_allow_origins == ["http://localhost:3000"]


class TestLogbookTileThrottle:
    """The basemap tile throttle must never be silently disabled.

    ``_TileThrottle`` treats a non-positive rate as "no pacing", so a bad
    ``LOGBOOK_TILE_THROTTLE_PER_SECOND`` would quietly violate OSM's
    tile-usage policy. Settings rejects it at startup instead.
    """

    def test_defaults_to_two_tiles_per_second(self, monkeypatch: pytest.MonkeyPatch):
        # ``_env_file=None`` only disables the dotenv file — pydantic-settings
        # still reads os.environ, so clear the var to assert the real default.
        monkeypatch.delenv("LOGBOOK_TILE_THROTTLE_PER_SECOND", raising=False)

        settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

        assert settings.logbook_tile_throttle_per_second == 2.0

    def test_accepts_a_positive_rate(self):
        settings = Settings(logbook_tile_throttle_per_second=0.5)

        assert settings.logbook_tile_throttle_per_second == 0.5

    def test_rejects_zero(self):
        with pytest.raises(ValidationError):
            Settings(logbook_tile_throttle_per_second=0)

    def test_rejects_a_negative_rate(self):
        with pytest.raises(ValidationError):
            Settings(logbook_tile_throttle_per_second=-1)
