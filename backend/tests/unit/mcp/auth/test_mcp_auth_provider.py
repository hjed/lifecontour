"""
Unit tests for MCP OAuth auth provider factory.

Tests that _create_mcp_auth_provider correctly selects the FastMCP
OAuth provider based on which OAuth credentials are configured.
"""

from typing import Any

import pytest

from app.infrastructure.config import Settings
from app.mcp.server import _create_mcp_auth_provider


class TestCreateMcpAuthProvider:
    """Tests for the _create_mcp_auth_provider factory function."""

    def _settings(self, **overrides: Any) -> Settings:
        """Create test settings with overrides."""
        defaults: dict[str, Any] = {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "mcp_base_url": "http://localhost:8000",
            "mcp_mount_path": "/mcp-server",
        }
        defaults.update(overrides)
        return Settings(**defaults)

    def test_returns_none_when_auth_disabled(self) -> None:
        """When disable_auth is True, no provider is created."""
        settings = self._settings(disable_auth=True)
        result = _create_mcp_auth_provider(settings)
        assert result is None

    def test_returns_none_when_no_providers_configured(self) -> None:
        """When no OAuth credentials are set and auth not disabled, returns None."""
        settings = self._settings()
        result = _create_mcp_auth_provider(settings)
        assert result is None

    def test_generic_oauth_preferred_over_github(self) -> None:
        """Generic OAuth provider is used when both generic and GitHub are configured."""
        settings = self._settings(
            oauth_client_id="generic-id",
            oauth_client_secret="generic-secret",
            oauth_authorization_url="https://auth.example.com/authorize",
            oauth_token_url="https://auth.example.com/token",
            oauth_introspection_url="https://auth.example.com/introspect",
            github_client_id="github-id",
            github_client_secret="github-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None

        from fastmcp.server.auth import OAuthProxy

        assert isinstance(result, OAuthProxy)

    def test_github_provider_when_configured(self) -> None:
        """GitHubProvider is returned when GitHub credentials are set."""
        settings = self._settings(
            github_client_id="gh-client-id",
            github_client_secret="gh-client-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None

        from fastmcp.server.auth.providers.github import GitHubProvider

        assert isinstance(result, GitHubProvider)

    def test_google_provider_when_configured(self) -> None:
        """GoogleProvider is returned when Google credentials are set."""
        settings = self._settings(
            google_client_id="google-client-id",
            google_client_secret="google-client-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None

        from fastmcp.server.auth.providers.google import GoogleProvider

        assert isinstance(result, GoogleProvider)

    def test_discord_provider_when_configured(self) -> None:
        """DiscordProvider is returned when Discord credentials are set."""
        settings = self._settings(
            discord_client_id="discord-client-id",
            discord_client_secret="discord-client-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None

        from fastmcp.server.auth.providers.discord import DiscordProvider

        assert isinstance(result, DiscordProvider)

    def test_provider_priority_github_over_google(self) -> None:
        """GitHub is chosen over Google when both are configured (no generic)."""
        settings = self._settings(
            github_client_id="gh-id",
            github_client_secret="gh-secret",
            google_client_id="g-id",
            google_client_secret="g-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None

        from fastmcp.server.auth.providers.github import GitHubProvider

        assert isinstance(result, GitHubProvider)

    def test_base_url_includes_mount_path(self) -> None:
        """Provider base_url includes both base URL and mount path."""
        settings = self._settings(
            mcp_base_url="https://example.com",
            mcp_mount_path="/mcp",
            github_client_id="gh-id",
            github_client_secret="gh-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None
        assert str(result.base_url) == "https://example.com/mcp"

    def test_base_url_normalized_trailing_slash(self) -> None:
        """Trailing slash on base URL and missing leading slash on mount path are handled."""
        settings = self._settings(
            mcp_base_url="https://example.com/",
            mcp_mount_path="mcp-server",
            github_client_id="gh-id",
            github_client_secret="gh-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None
        assert str(result.base_url) == "https://example.com/mcp-server"

    def test_base_url_normalized_double_slash(self) -> None:
        """Double slashes between base URL and mount path are prevented."""
        settings = self._settings(
            mcp_base_url="https://example.com/",
            mcp_mount_path="/mcp-server",
            github_client_id="gh-id",
            github_client_secret="gh-secret",
        )
        result = _create_mcp_auth_provider(settings)
        assert result is not None
        assert str(result.base_url) == "https://example.com/mcp-server"

    def test_generic_oauth_requires_introspection_url(self) -> None:
        """Generic OAuth is not selected when introspection URL is missing."""
        settings = self._settings(
            oauth_client_id="generic-id",
            oauth_client_secret="generic-secret",
            oauth_authorization_url="https://auth.example.com/authorize",
            oauth_token_url="https://auth.example.com/token",
            # Missing oauth_introspection_url — falls through to None
        )
        result = _create_mcp_auth_provider(settings)
        assert result is None

    @pytest.mark.parametrize(
        "missing_field",
        [
            "oauth_authorization_url",
            "oauth_token_url",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_introspection_url",
        ],
    )
    def test_generic_oauth_skipped_with_missing_field(self, missing_field: str) -> None:
        """Generic OAuth is skipped when any required field is empty."""
        fields = {
            "oauth_client_id": "id",
            "oauth_client_secret": "secret",
            "oauth_authorization_url": "https://auth.example.com/authorize",
            "oauth_token_url": "https://auth.example.com/token",
            "oauth_introspection_url": "https://auth.example.com/introspect",
        }
        fields[missing_field] = ""
        # With only generic OAuth fields (some missing), should return None
        # because no fallback provider is configured either
        result = _create_mcp_auth_provider(self._settings(**fields))
        assert result is None
