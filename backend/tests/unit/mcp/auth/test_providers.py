"""
Unit tests for MCP auth provider factory.

Tests that create_mcp_auth_provider() returns the correct provider
based on configured OAuth settings.
"""

from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.discord import DiscordProvider
from fastmcp.server.auth.providers.github import GitHubProvider
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from app.infrastructure.config import Settings
from app.mcp.auth.providers import (
    _LoggingFernetEncryptionWrapper,
    create_mcp_auth_provider,
)


def _generic_settings(**overrides: object) -> Settings:
    """Settings with a fully configured generic OAuth provider."""
    base: dict[str, object] = {
        "oauth_client_id": "generic-id",
        "oauth_client_secret": "generic-secret",
        "oauth_authorization_url": "https://auth.example.com/authorize",
        "oauth_token_url": "https://auth.example.com/token",
    }
    base.update(overrides)
    return _settings(**base)


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


class TestGenericOAuthRefreshConfig:
    """Generic OAuth proxy is wired for auto-refresh and persistent storage."""

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_default_scope_excludes_offline_access(self, mock_init: MagicMock) -> None:
        """Default scope stays provider-safe (no offline_access for Kanidm)."""
        create_mcp_auth_provider(_generic_settings())
        kwargs = mock_init.call_args.kwargs
        assert kwargs["extra_authorize_params"] == {"scope": "openid profile email"}

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_offline_access_scope_passed_through_when_configured(
        self, mock_init: MagicMock
    ) -> None:
        """offline_access (dev/Hydra) is forwarded when set via settings."""
        settings = _generic_settings(oauth_scopes="openid profile email offline_access")
        create_mcp_auth_provider(settings)
        kwargs = mock_init.call_args.kwargs
        assert kwargs["extra_authorize_params"] == {
            "scope": "openid profile email offline_access"
        }

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_refresh_threshold_default_passed(self, mock_init: MagicMock) -> None:
        """Proactive refresh threshold defaults to 60s and is forwarded."""
        create_mcp_auth_provider(_generic_settings())
        assert mock_init.call_args.kwargs["token_expiry_threshold_seconds"] == 60

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_refresh_threshold_override_passed(self, mock_init: MagicMock) -> None:
        """An overridden refresh threshold flows through to OAuthProxy."""
        settings = _generic_settings(oauth_token_refresh_threshold_seconds=120)
        create_mcp_auth_provider(settings)
        assert mock_init.call_args.kwargs["token_expiry_threshold_seconds"] == 120

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_jwt_signing_key_passed_when_set(self, mock_init: MagicMock) -> None:
        """A configured signing key is pinned on the proxy."""
        settings = _generic_settings(mcp_jwt_signing_key="pinned-secret")
        create_mcp_auth_provider(settings)
        assert mock_init.call_args.kwargs["jwt_signing_key"] == "pinned-secret"

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_jwt_signing_key_none_when_empty(self, mock_init: MagicMock) -> None:
        """Empty signing key falls back to FastMCP's HKDF behaviour (None)."""
        create_mcp_auth_provider(_generic_settings(mcp_jwt_signing_key=""))
        assert mock_init.call_args.kwargs["jwt_signing_key"] is None

    @patch("app.mcp.auth.providers.RedisStore")
    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_redis_client_storage_used_when_enabled(
        self, mock_init: MagicMock, mock_redis: MagicMock
    ) -> None:
        """Redis-backed, Fernet-wrapped storage is built when enabled + keyed."""
        settings = _generic_settings(
            mcp_oauth_use_redis_storage=True,
            mcp_jwt_signing_key="pinned-secret",
            redis_url="redis://cache:6379",
        )
        create_mcp_auth_provider(settings)
        mock_redis.assert_called_once()
        storage = mock_init.call_args.kwargs["client_storage"]
        assert isinstance(storage, FernetEncryptionWrapper)

    @patch("app.mcp.auth.providers.RedisStore")
    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_no_redis_storage_when_disabled(
        self, mock_init: MagicMock, mock_redis: MagicMock
    ) -> None:
        """Disabling redis storage falls back to FastMCP's file store (None)."""
        settings = _generic_settings(
            mcp_oauth_use_redis_storage=False,
            mcp_jwt_signing_key="pinned-secret",
        )
        create_mcp_auth_provider(settings)
        mock_redis.assert_not_called()
        assert mock_init.call_args.kwargs["client_storage"] is None

    @patch("app.mcp.auth.providers.RedisStore")
    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_no_redis_storage_without_signing_key(
        self, mock_init: MagicMock, mock_redis: MagicMock
    ) -> None:
        """Without a signing key we cannot encrypt; fall back to file store."""
        settings = _generic_settings(
            mcp_oauth_use_redis_storage=True,
            mcp_jwt_signing_key="",
        )
        create_mcp_auth_provider(settings)
        mock_redis.assert_not_called()
        assert mock_init.call_args.kwargs["client_storage"] is None


class TestLoggingFernetEncryptionWrapper:
    """The storage wrapper surfaces decryption failures instead of hiding them."""

    def _encrypted_payload(self, key: bytes) -> dict[str, object]:
        """Encrypt a payload with the given Fernet key."""
        encoder = FernetEncryptionWrapper(
            key_value=MagicMock(),
            fernet=Fernet(key=key),
        )
        return encoder._encrypt_value({"refresh_token": "secret"})

    def test_decrypt_failure_logs_warning(self) -> None:
        """A key mismatch is logged (not silently dropped) and yields None."""
        payload = self._encrypted_payload(Fernet.generate_key())
        # Wrap with a DIFFERENT key so decryption fails.
        wrapper = _LoggingFernetEncryptionWrapper(
            key_value=MagicMock(),
            fernet=Fernet(key=Fernet.generate_key()),
            raise_on_decryption_error=False,
        )
        with patch("app.mcp.auth.providers.logger") as mock_logger:
            result = wrapper._decrypt_value(payload)
        assert result is None
        mock_logger.warning.assert_called_once()

    def test_decrypt_success_does_not_warn(self) -> None:
        """A successful round-trip returns the value and logs nothing."""
        key = Fernet.generate_key()
        payload = self._encrypted_payload(key)
        wrapper = _LoggingFernetEncryptionWrapper(
            key_value=MagicMock(),
            fernet=Fernet(key=key),
            raise_on_decryption_error=False,
        )
        with patch("app.mcp.auth.providers.logger") as mock_logger:
            result = wrapper._decrypt_value(payload)
        assert result == {"refresh_token": "secret"}
        mock_logger.warning.assert_not_called()

    def test_missing_value_does_not_warn(self) -> None:
        """A genuine cache miss (None input) is not treated as a failure."""
        wrapper = _LoggingFernetEncryptionWrapper(
            key_value=MagicMock(),
            fernet=Fernet(key=Fernet.generate_key()),
            raise_on_decryption_error=False,
        )
        with patch("app.mcp.auth.providers.logger") as mock_logger:
            result = wrapper._decrypt_value(None)
        assert result is None
        mock_logger.warning.assert_not_called()
