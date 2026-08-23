"""Unit tests for the MCP OAuth proxy's upstream-identity extraction.

The generic-OAuth branch pairs ``OAuthProxy`` with ``DebugTokenVerifier``, whose
``AccessToken`` carries no ``sub``, no ``id`` and no ``email`` — only the raw
upstream token. Without an identity of its own every MCP request resolved to the
verifier's hard-coded ``client_id`` default, so every MCP write landed on a
phantom owner shared by every user.

``UpstreamIdentityOAuthProxy`` closes that by implementing FastMCP's
``_extract_upstream_claims`` hook: the upstream ``id_token`` is decoded at
exchange time and its identity claims are embedded in the FastMCP JWT, which
FastMCP re-attaches to ``AccessToken.claims["upstream_claims"]`` on every
verified request.
"""

import base64
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy

from app.infrastructure.config import Settings
from app.mcp.auth.providers import (
    UpstreamIdentityOAuthProxy,
    create_mcp_auth_provider,
)


def _jwt(payload: dict[str, Any]) -> str:
    """Build an unsigned JWT whose payload decodes to ``payload``."""

    def segment(data: dict[str, Any]) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{segment({'alg': 'RS256', 'typ': 'JWT'})}.{segment(payload)}.signature"


def _generic_settings(**overrides: object) -> Settings:
    """Settings with a fully configured generic OAuth provider."""
    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "webhook_base_url": "https://example.com",
        "mcp_mount_path": "/mcp-server",
        "disable_auth": False,
        "oauth_client_id": "generic-id",
        "oauth_client_secret": "generic-secret",
        "oauth_authorization_url": "https://auth.example.com/authorize",
        "oauth_token_url": "https://auth.example.com/token",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _proxy() -> UpstreamIdentityOAuthProxy:
    """An instance whose ``__init__`` is stubbed out (we only call the hook)."""
    with patch.object(OAuthProxy, "__init__", return_value=None):
        return UpstreamIdentityOAuthProxy(
            upstream_authorization_endpoint="https://auth.example.com/authorize",
            upstream_token_endpoint="https://auth.example.com/token",
            upstream_client_id="generic-id",
            upstream_client_secret="generic-secret",
            token_verifier=MagicMock(),
            base_url="https://example.com",
        )


class TestGenericProviderUsesTheSubclass:
    """The generic-OAuth branch must build the identity-aware proxy."""

    @patch("app.mcp.auth.providers.OAuthProxy.__init__", return_value=None)
    def test_generic_oauth_builds_upstream_identity_proxy(
        self, _mock_init: MagicMock
    ) -> None:
        result = create_mcp_auth_provider(_generic_settings())
        assert isinstance(result, UpstreamIdentityOAuthProxy)


class TestExtractUpstreamClaims:
    """The upstream id_token is the source of MCP user identity."""

    async def test_extracts_identity_claims_from_the_id_token(self) -> None:
        tokens = {
            "access_token": "opaque-upstream-token",
            "id_token": _jwt(
                {
                    "sub": "9f1c1f0e-0000-4000-8000-abcdefabcdef",
                    "email": "person@example.com",
                    "name": "A Person",
                    "preferred_username": "person",
                    "aud": "generic-id",
                }
            ),
        }

        claims = await _proxy()._extract_upstream_claims(tokens)

        assert claims is not None
        assert claims["sub"] == "9f1c1f0e-0000-4000-8000-abcdefabcdef"
        assert claims["email"] == "person@example.com"
        assert claims["name"] == "A Person"
        assert claims["preferred_username"] == "person"

    async def test_omits_claims_the_id_token_does_not_carry(self) -> None:
        tokens = {"id_token": _jwt({"sub": "only-a-subject"})}

        claims = await _proxy()._extract_upstream_claims(tokens)

        assert claims == {"sub": "only-a-subject"}

    async def test_prefers_the_id_token_over_the_access_token(self) -> None:
        """An opaque access token must not shadow the id_token's identity."""
        tokens = {
            "access_token": "not-a-jwt",
            "id_token": _jwt({"sub": "from-id-token"}),
        }

        claims = await _proxy()._extract_upstream_claims(tokens)

        assert claims is not None
        assert claims["sub"] == "from-id-token"

    async def test_falls_back_to_a_jwt_access_token_when_no_id_token(self) -> None:
        """Providers that skip the id_token still identify via a JWT access token."""
        tokens = {"access_token": _jwt({"sub": "from-access-token"})}

        claims = await _proxy()._extract_upstream_claims(tokens)

        assert claims is not None
        assert claims["sub"] == "from-access-token"

    @pytest.mark.parametrize(
        "tokens",
        [
            pytest.param({}, id="no-tokens"),
            pytest.param({"access_token": "opaque"}, id="opaque-access-token"),
            pytest.param({"id_token": "not.a.jwt"}, id="undecodable-id-token"),
            pytest.param({"id_token": _jwt({"email": "a@b.com"})}, id="no-subject"),
        ],
    )
    async def test_returns_none_when_no_subject_can_be_found(
        self, tokens: dict[str, Any]
    ) -> None:
        """No identity is better than a wrong one — the request then 401s."""
        assert await _proxy()._extract_upstream_claims(tokens) is None
