"""
Unit tests for MCP auth provider factory.

Tests that create_mcp_auth_provider() returns the correct provider
based on configured OAuth settings.
"""

import base64
import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.discord import DiscordProvider
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from app.infrastructure.config import Settings
from app.mcp.auth.providers import (
    McpOidcProxy,
    _IdTokenVerifier,
    _LoggingFernetEncryptionWrapper,
    create_mcp_auth_provider,
)


def _generic_settings(**overrides: object) -> Settings:
    """Settings with a fully configured generic OAuth provider.

    The authorization and token endpoints are no longer read from settings on
    the MCP path — they come from the discovery document — but they stay here
    because the REST web-login flow still uses them.
    """
    base: dict[str, object] = {
        "oauth_client_id": "generic-id",
        "oauth_client_secret": "generic-secret",
        "oauth_authorization_url": "https://auth.example.com/authorize",
        "oauth_token_url": "https://auth.example.com/token",
        "oauth_issuer": "https://auth.example.com",
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

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_generic_oauth_is_highest_priority(self, mock_init: object) -> None:
        """Generic OAuth provider should be chosen over named providers."""
        settings = _generic_settings(
            github_client_id="gh-id",
            github_client_secret="gh-secret",
        )
        result = create_mcp_auth_provider(settings)
        assert isinstance(result, McpOidcProxy)

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

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_default_scope_excludes_offline_access(self, mock_init: MagicMock) -> None:
        """Default scope stays provider-safe (no offline_access for Kanidm)."""
        create_mcp_auth_provider(_generic_settings())
        kwargs = mock_init.call_args.kwargs
        assert kwargs["extra_authorize_params"] == {"scope": "openid profile email"}

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
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

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_refresh_threshold_default_passed(self, mock_init: MagicMock) -> None:
        """Proactive refresh threshold defaults to 60s and is forwarded."""
        create_mcp_auth_provider(_generic_settings())
        assert mock_init.call_args.kwargs["token_expiry_threshold_seconds"] == 60

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_refresh_threshold_override_passed(self, mock_init: MagicMock) -> None:
        """An overridden refresh threshold flows through to OAuthProxy."""
        settings = _generic_settings(oauth_token_refresh_threshold_seconds=120)
        create_mcp_auth_provider(settings)
        assert mock_init.call_args.kwargs["token_expiry_threshold_seconds"] == 120

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_jwt_signing_key_passed_when_set(self, mock_init: MagicMock) -> None:
        """A configured signing key is pinned on the proxy."""
        settings = _generic_settings(mcp_jwt_signing_key="pinned-secret")
        create_mcp_auth_provider(settings)
        assert mock_init.call_args.kwargs["jwt_signing_key"] == "pinned-secret"

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_jwt_signing_key_none_when_empty(self, mock_init: MagicMock) -> None:
        """Empty signing key falls back to FastMCP's HKDF behaviour (None)."""
        create_mcp_auth_provider(_generic_settings(mcp_jwt_signing_key=""))
        assert mock_init.call_args.kwargs["jwt_signing_key"] is None

    @patch("app.mcp.auth.providers.RedisStore")
    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
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
    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
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
    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
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


# A discovery document shaped like a real one. Kanidm advertises ES256 only,
# which is the case that matters: FastMCP's JWTVerifier silently defaults to
# RS256, so an unselected algorithm would reject every production token.
_KANIDM_DOCUMENT: dict[str, object] = {
    "issuer": "https://auth.example.com",
    "authorization_endpoint": "https://auth.example.com/oauth2/authorise",
    "token_endpoint": "https://auth.example.com/oauth2/token",
    "jwks_uri": "https://auth.example.com/oauth2/openid/pms/public_key.jwk",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["ES256"],
}


def _document(**overrides: object) -> OIDCConfiguration:
    return OIDCConfiguration.model_validate({**_KANIDM_DOCUMENT, **overrides})


def _hook_proxy(
    document: OIDCConfiguration, settings: Settings | None = None
) -> McpOidcProxy:
    """An instance with only what the overridden hooks read.

    ``__init__`` performs live OIDC discovery, so these tests exercise the two
    hooks directly rather than standing up a whole proxy.
    """
    proxy = McpOidcProxy.__new__(McpOidcProxy)
    proxy._settings = settings or _generic_settings()
    proxy.oidc_config = document
    return proxy


def _verifier(proxy: McpOidcProxy, **kwargs: Any) -> JWTVerifier:
    """The verifier the proxy would hand to FastMCP, narrowed for assertions."""
    verifier = proxy.get_token_verifier(**kwargs)
    assert isinstance(verifier, JWTVerifier)
    return verifier


class TestGenericOAuthTokenVerification:
    """The generic branch verifies upstream tokens against the IdP's JWKS."""

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_discovery_url_is_derived_from_the_issuer(
        self, mock_init: MagicMock
    ) -> None:
        create_mcp_auth_provider(_generic_settings())
        assert mock_init.call_args.kwargs["config_url"] == (
            "https://auth.example.com/.well-known/openid-configuration"
        )

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_an_explicit_discovery_url_wins(self, mock_init: MagicMock) -> None:
        """The dev stack fetches metadata from a container-internal address."""
        settings = _generic_settings(
            oauth_issuer="http://localhost:4444",
            oauth_discovery_url=(
                "http://pms-oauth:4444/.well-known/openid-configuration"
            ),
        )
        create_mcp_auth_provider(settings)
        assert mock_init.call_args.kwargs["config_url"] == (
            "http://pms-oauth:4444/.well-known/openid-configuration"
        )

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_verifies_the_id_token_not_the_access_token(
        self, mock_init: MagicMock
    ) -> None:
        """Hydra issues opaque access tokens; only the id_token is a JWT."""
        create_mcp_auth_provider(_generic_settings())
        assert mock_init.call_args.kwargs["verify_id_token"] is True

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_upstream_client_credentials_are_forwarded(
        self, mock_init: MagicMock
    ) -> None:
        create_mcp_auth_provider(_generic_settings())
        kwargs = mock_init.call_args.kwargs
        assert kwargs["client_id"] == "generic-id"
        assert kwargs["client_secret"] == "generic-secret"

    @patch("app.mcp.auth.providers.McpOidcProxy.__init__", return_value=None)
    def test_settings_are_passed_for_the_issuer_cross_check(
        self, mock_init: MagicMock
    ) -> None:
        settings = _generic_settings()
        create_mcp_auth_provider(settings)
        assert mock_init.call_args.kwargs["settings"] is settings

    def test_raises_when_the_issuer_is_not_configured(self) -> None:
        """Never fall back to accepting every token, which is the old bug."""
        settings = _settings(
            oauth_client_id="generic-id",
            oauth_client_secret="generic-secret",
            oauth_authorization_url="https://auth.example.com/authorize",
            oauth_token_url="https://auth.example.com/token",
        )
        with pytest.raises(RuntimeError, match="OAUTH_ISSUER"):
            create_mcp_auth_provider(settings)

    def test_does_not_silently_fall_through_to_a_named_provider(self) -> None:
        """A misconfigured generic provider must not degrade to GitHub."""
        settings = _settings(
            oauth_client_id="generic-id",
            oauth_client_secret="generic-secret",
            github_client_id="gh-id",
            github_client_secret="gh-secret",
        )
        with pytest.raises(RuntimeError, match="OAUTH_ISSUER"):
            create_mcp_auth_provider(settings)


class TestMcpOidcProxyTokenVerifier:
    """The verifier follows the algorithm the IdP actually advertises."""

    def test_algorithm_comes_from_the_discovery_document(self) -> None:
        verifier = _verifier(_hook_proxy(_document()), audience="generic-id")
        assert verifier.algorithm == "ES256"

    def test_first_advertised_supported_algorithm_wins(self) -> None:
        """IdPs list their signing default first."""
        document = _document(
            id_token_signing_alg_values_supported=["RS256", "ES256"],
        )
        assert _verifier(_hook_proxy(document)).algorithm == "RS256"

    def test_an_explicit_algorithm_is_not_overridden(self) -> None:
        verifier = _verifier(_hook_proxy(_document()), algorithm="RS384")
        assert verifier.algorithm == "RS384"

    def test_raises_when_no_advertised_algorithm_is_supported(self) -> None:
        document = _document(id_token_signing_alg_values_supported=["EdDSA"])
        with pytest.raises(RuntimeError, match="signing algorithm"):
            _verifier(_hook_proxy(document))

    def test_jwks_and_issuer_come_from_the_document(self) -> None:
        """The issuer must survive verbatim.

        ``JWTVerifier`` compares it to the token's ``iss`` with ``==``, so a
        bare origin that picked up a normalising trailing slash on the way
        through would reject every token the IdP issues.
        """
        verifier = _verifier(_hook_proxy(_document()), audience="generic-id")
        assert verifier.jwks_uri == (
            "https://auth.example.com/oauth2/openid/pms/public_key.jwk"
        )
        assert verifier.issuer == "https://auth.example.com"
        assert verifier.audience == "generic-id"


class TestMcpOidcProxyIssuerCrossCheck:
    """A document that disagrees with OAUTH_ISSUER must not be trusted."""

    def _get_config(self, document: OIDCConfiguration, settings: Settings) -> object:
        proxy = _hook_proxy(document, settings)
        with patch.object(
            OIDCConfiguration, "get_oidc_configuration", return_value=document
        ):
            return proxy.get_oidc_configuration(
                "https://auth.example.com/.well-known/openid-configuration",  # type: ignore[arg-type]
                None,
                10,
            )

    def test_accepts_a_matching_issuer(self) -> None:
        settings = _generic_settings(oauth_issuer="https://auth.example.com")
        assert self._get_config(_document(), settings) is not None

    def test_rejects_a_mismatched_issuer(self) -> None:
        """A mispointed document could otherwise supply attacker-owned keys."""
        settings = _generic_settings(oauth_issuer="https://auth.example.com")
        document = _document(issuer="https://evil.example.com")
        with pytest.raises(RuntimeError, match="issuer mismatch"):
            self._get_config(document, settings)


class TestGenericOAuthEndToEndConstruction:
    """Build the real proxy against a stubbed discovery document."""

    def test_builds_a_proxy_that_verifies_es256_id_tokens(self) -> None:
        settings = _generic_settings(
            mcp_jwt_signing_key="pinned-secret",
            mcp_oauth_use_redis_storage=False,
        )
        with patch.object(
            OIDCConfiguration, "get_oidc_configuration", return_value=_document()
        ):
            provider = create_mcp_auth_provider(settings)

        assert isinstance(provider, McpOidcProxy)
        # The id_token is the verified token, and its `aud` is the client_id
        # (OIDC Core 2), not an API resource identifier.
        assert provider._verify_id_token is True
        verifier = provider._token_validator
        assert isinstance(verifier, JWTVerifier)
        assert verifier.algorithm == "ES256"
        assert verifier.audience == "generic-id"


def _jwt(**claims: Any) -> str:
    """An unsigned JWT whose payload decodes to ``claims``."""

    def segment(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{segment({'alg': 'RS256'})}.{segment(claims)}.signature"


def _token_set(id_token: str | None, access_token_expires_in: float) -> MagicMock:
    """An upstream token set as FastMCP stores it after an exchange or refresh."""
    token_set = MagicMock()
    token_set.raw_token_data = {} if id_token is None else {"id_token": id_token}
    token_set.access_token = "opaque-upstream-token"
    token_set.expires_at = time.time() + access_token_expires_in
    return token_set


class TestStaleIdTokenIsDiagnosable:
    """A refresh that omits id_token leaves the previous one behind.

    OIDC permits it, and FastMCP merges each refresh response into
    ``raw_token_data`` — so the access token's expiry is reset while the old
    id_token stays put. Verification then fails, and the refresh that would
    replace the id_token is not due again until the fresh access token nears
    expiry, so the session 401s for that whole window with nothing in the log
    to explain it.
    """

    def _verification_token(
        self, token_set: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> str | None:
        proxy = _hook_proxy(_document())
        proxy._verify_id_token = True
        with caplog.at_level("WARNING"):
            return proxy._get_verification_token(token_set)

    def test_warns_when_the_id_token_outlives_its_usefulness(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        token_set = _token_set(_jwt(exp=time.time() - 60), access_token_expires_in=3000)

        token = self._verification_token(token_set, caplog)

        # Still returned: this diagnoses, it does not change what is verified.
        assert token == token_set.raw_token_data["id_token"]
        assert "omitted id_token from a refresh response" in caplog.text

    def test_silent_when_the_id_token_is_still_valid(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        token_set = _token_set(
            _jwt(exp=time.time() + 3000), access_token_expires_in=3000
        )

        assert self._verification_token(token_set, caplog) is not None
        assert "refresh response" not in caplog.text

    def test_silent_when_both_tokens_have_expired(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Ordinary expiry, not the merge trap — refresh is due and will fix it."""
        token_set = _token_set(_jwt(exp=time.time() - 60), access_token_expires_in=-60)

        assert self._verification_token(token_set, caplog) is not None
        assert "refresh response" not in caplog.text

    def test_silent_when_the_id_token_carries_no_expiry(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        token_set = _token_set(_jwt(sub="a-user"), access_token_expires_in=3000)

        assert self._verification_token(token_set, caplog) is not None
        assert "refresh response" not in caplog.text

    def test_undecodable_id_token_is_passed_through_without_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Let the verifier reject it; there is nothing to diagnose here."""
        token_set = _token_set("not.a.jwt", access_token_expires_in=3000)

        assert self._verification_token(token_set, caplog) == "not.a.jwt"
        assert "refresh response" not in caplog.text

    def test_no_id_token_at_all_is_left_to_fastmcp(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        token_set = _token_set(None, access_token_expires_in=3000)

        assert self._verification_token(token_set, caplog) is None


def _verified(**claims: Any) -> AccessToken:
    """What ``JWTVerifier`` hands back once the signature has checked out."""
    return AccessToken(
        token="signed-id-token",
        client_id=str(claims.get("azp") or claims.get("aud") or "generic-id"),
        scopes=[],
        expires_at=None,
        claims=claims,
    )


async def _verify(**claims: Any) -> AccessToken | None:
    """Run only the OIDC ID Token rules, with the signature check stubbed out."""
    verifier = _IdTokenVerifier(
        authorized_party="generic-id",
        jwks_uri="https://auth.example.com/jwks",
        issuer="https://auth.example.com",
        algorithm="ES256",
    )
    with patch.object(
        JWTVerifier, "load_access_token", return_value=_verified(**claims)
    ):
        return await verifier.load_access_token("signed-id-token")


class TestIdTokenExpiryIsMandatory:
    """OIDC Core 2 makes `exp` REQUIRED; JWTVerifier only checks it when present.

    An ID Token without one would authenticate forever, outliving the upstream
    grant it stands for and surviving the refresh failure that otherwise ends a
    dead session.
    """

    async def test_rejects_a_token_with_no_expiry(self) -> None:
        assert await _verify(sub="a-user", aud="generic-id") is None

    async def test_accepts_a_token_that_carries_one(self) -> None:
        assert await _verify(sub="a-user", aud="generic-id", exp=1) is not None

    async def test_a_failed_signature_check_still_short_circuits(self) -> None:
        verifier = _IdTokenVerifier(
            authorized_party="generic-id",
            jwks_uri="https://auth.example.com/jwks",
            issuer="https://auth.example.com",
        )
        with patch.object(JWTVerifier, "load_access_token", return_value=None):
            assert await verifier.load_access_token("nonsense") is None


class TestAuthorizedPartyIsEnforced:
    """OIDC Core 3.1.3.7: `azp` must be this client when it is present.

    JWTVerifier only checks that our client id appears *somewhere* in `aud`, so
    without this a token minted for another relying party that happens to list
    us alongside itself would authenticate here.
    """

    async def test_rejects_a_token_issued_to_another_relying_party(self) -> None:
        token = await _verify(
            sub="a-user",
            aud=["other-rp", "generic-id"],
            azp="other-rp",
            exp=1,
        )
        assert token is None

    async def test_accepts_a_token_whose_azp_is_this_client(self) -> None:
        token = await _verify(
            sub="a-user",
            aud=["other-rp", "generic-id"],
            azp="generic-id",
            exp=1,
        )
        assert token is not None

    async def test_rejects_several_audiences_with_no_azp(self) -> None:
        """Nothing then establishes which party the token was issued to."""
        token = await _verify(sub="a-user", aud=["other-rp", "generic-id"], exp=1)
        assert token is None

    async def test_a_single_audience_needs_no_azp(self) -> None:
        """The common case: `aud` alone identifies the party."""
        assert await _verify(sub="a-user", aud="generic-id", exp=1) is not None

    async def test_a_single_audience_in_a_list_needs_no_azp(self) -> None:
        assert await _verify(sub="a-user", aud=["generic-id"], exp=1) is not None


class TestProxyBuildsTheStrictVerifier:
    def test_the_verifier_enforces_the_oidc_id_token_rules(self) -> None:
        verifier = _hook_proxy(_document()).get_token_verifier(audience="generic-id")
        assert isinstance(verifier, _IdTokenVerifier)

    def test_the_authorized_party_is_the_configured_client(self) -> None:
        verifier = _hook_proxy(_document()).get_token_verifier(audience="generic-id")
        assert isinstance(verifier, _IdTokenVerifier)
        assert verifier._authorized_party == "generic-id"
