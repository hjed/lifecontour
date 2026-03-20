"""
Unit tests for MCP auth provider factory.

Tests that create_mcp_auth_provider() returns the correct provider
based on configured OAuth settings.
"""

from unittest.mock import patch

from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.discord import DiscordProvider
from fastmcp.server.auth.providers.github import GitHubProvider

from app.infrastructure.config import Settings
from app.mcp.auth.providers import create_mcp_auth_provider


def _settings(**overrides: object) -> Settings:
    """Create Settings with sensible defaults and overrides."""
    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "webhook_base_url": "https://example.com",
        "mcp_mount_path": "/mcp-server",
        "disable_auth": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestCreateMCPAuthProvider:
    """Test MCP auth provider factory function."""

    def test_returns_none_when_auth_disabled(self) -> None:
        """Auth disabled should return None regardless of configured providers."""
        settings = _settings(
            disable_auth=True,
            github_client_id="id",
            github_client_secret="secret",
        )
        result = create_mcp_auth_provider(settings)
        assert result is None

    def test_returns_none_when_no_providers_configured(self) -> None:
        """No configured OAuth providers should return None."""
        settings = _settings()
        result = create_mcp_auth_provider(settings)
        assert result is None

    def test_raises_when_no_webhook_base_url_but_providers_configured(
        self,
    ) -> None:
        """Missing webhook_base_url with configured providers should raise."""
        import pytest

        settings = _settings(
            webhook_base_url="",
            github_client_id="id",
            github_client_secret="secret",
        )
        with pytest.raises(RuntimeError, match="WEBHOOK_BASE_URL"):
            create_mcp_auth_provider(settings)

    def test_returns_none_when_no_webhook_base_url_and_no_providers(self) -> None:
        """Missing webhook_base_url without any providers should return None."""
        settings = _settings(webhook_base_url="")
        result = create_mcp_auth_provider(settings)
        assert result is None

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_generic_oauth_is_highest_priority(self, mock_init: object) -> None:
        """Generic OAuth provider should be chosen over named providers."""
        settings = _settings(
            oauth_client_id="generic-id",
            oauth_client_secret="generic-secret",
            oauth_authorization_url="https://auth.example.com/authorize",
            oauth_token_url="https://auth.example.com/token",
            github_client_id="gh-id",
            github_client_secret="gh-secret",
        )
        result = create_mcp_auth_provider(settings)
        assert isinstance(result, OAuthProxy)

    @patch("app.mcp.auth.providers.GitHubProvider.__init__", return_value=None)
    def test_github_provider_created(self, mock_init: object) -> None:
        """GitHub provider should be created when configured."""
        settings = _settings(
            github_client_id="gh-id",
            github_client_secret="gh-secret",
        )
        result = create_mcp_auth_provider(settings)
        assert isinstance(result, GitHubProvider)

    @patch("app.mcp.auth.providers.AzureProvider.__init__", return_value=None)
    def test_microsoft_provider_created(self, mock_init: object) -> None:
        """Azure provider should be created for Microsoft OAuth."""
        settings = _settings(
            microsoft_client_id="ms-id",
            microsoft_client_secret="ms-secret",
            microsoft_tenant_id="my-tenant",
        )
        result = create_mcp_auth_provider(settings)
        assert isinstance(result, AzureProvider)

    @patch("app.mcp.auth.providers.DiscordProvider.__init__", return_value=None)
    def test_discord_provider_created(self, mock_init: object) -> None:
        """Discord provider should be created when configured."""
        settings = _settings(
            discord_client_id="dc-id",
            discord_client_secret="dc-secret",
        )
        result = create_mcp_auth_provider(settings)
        assert isinstance(result, DiscordProvider)

    @patch("app.mcp.auth.providers.GitHubProvider.__init__", return_value=None)
    def test_github_before_microsoft(self, mock_init: object) -> None:
        """GitHub should have higher priority than Microsoft."""
        settings = _settings(
            github_client_id="gh-id",
            github_client_secret="gh-secret",
            microsoft_client_id="ms-id",
            microsoft_client_secret="ms-secret",
        )
        result = create_mcp_auth_provider(settings)
        assert isinstance(result, GitHubProvider)

    @patch("app.mcp.auth.providers.AzureProvider.__init__", return_value=None)
    def test_microsoft_before_discord(self, mock_init: object) -> None:
        """Microsoft should have higher priority than Discord."""
        settings = _settings(
            microsoft_client_id="ms-id",
            microsoft_client_secret="ms-secret",
            discord_client_id="dc-id",
            discord_client_secret="dc-secret",
        )
        result = create_mcp_auth_provider(settings)
        assert isinstance(result, AzureProvider)
