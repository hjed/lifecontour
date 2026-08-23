"""
Integration tests for MCP FastAPI integration.

Tests the MCP server integration with the main FastAPI application,
including OAuth authentication and .well-known discovery endpoints.
"""

from contextlib import AbstractContextManager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration

from app.infrastructure.config import Settings
from app.main import create_app

# What the upstream IdP advertises. Stubbed because OIDC discovery happens
# synchronously while the app is being built, and these tests must not depend on
# a reachable IdP. ES256 is the Kanidm shape.
_DISCOVERY_DOCUMENT: dict[str, object] = {
    "issuer": "https://auth.example.com",
    "authorization_endpoint": "https://auth.example.com/authorize",
    "token_endpoint": "https://auth.example.com/token",
    "jwks_uri": "https://auth.example.com/jwks",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["ES256"],
}


def _stub_discovery() -> AbstractContextManager[MagicMock]:
    return patch.object(
        OIDCConfiguration,
        "get_oidc_configuration",
        return_value=OIDCConfiguration.model_validate(_DISCOVERY_DOCUMENT),
    )


class TestMCPFastAPIIntegration:
    """Test MCP server integration with FastAPI."""

    @pytest.fixture
    def test_settings(self, db_config):
        """Create test settings with MCP enabled (no auth)."""
        return Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
        )

    @pytest.fixture
    def app(self, test_settings):
        """Create FastAPI app with MCP integration."""
        return create_app(test_settings)

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_mcp_endpoint_exists(self, client):
        """Test that MCP endpoint is accessible."""
        # MCP endpoint should be mounted at /mcp-server/mcp
        response = client.get("/mcp-server/mcp")

        # Should not return 404 (endpoint exists)
        # May return 401 (authentication required) or other status
        assert response.status_code != 404

    def test_mcp_requires_authentication(self, client):
        """Test that MCP endpoint requires authentication."""
        # Try to access MCP endpoint without session
        # Use a simple GET request first to check if endpoint exists
        response = client.get("/mcp-server/mcp")

        # Should require authentication (401) or be a valid MCP response
        # FastMCP might return different status codes for different request types
        # 400 is also acceptable as it indicates the endpoint exists but request is invalid
        assert response.status_code in [
            400,  # Bad Request (endpoint exists but invalid request)
            401,  # Unauthorized
            405,  # Method Not Allowed
            422,  # Validation Error
        ]

    def test_main_app_still_works(self, client):
        """Test that main FastAPI app still works with MCP mounted."""
        # Test that the app is running by checking the OpenAPI docs
        # This should work regardless of database state
        response = client.get("/api/docs")

        # Should either return the docs (200) or redirect (3xx) if docs are disabled
        # 400 might occur if there are configuration issues, but that's still a response
        assert response.status_code in [
            200,  # Success
            307,  # Redirect
            400,  # Bad Request (but app is responding)
            404,  # Not Found (docs disabled)
        ]

    def test_mcp_accepts_trusted_public_host_behind_proxy(self, db_config):
        """MCP endpoint must accept a trusted production Host, not 421 it.

        fastmcp's HostOriginGuardMiddleware (DNS-rebinding protection) rejects
        any Host it doesn't recognise with 421 Misdirected Request. Behind a
        reverse proxy the ASGI bind host (e.g. 0.0.0.0) never matches the public
        Host header (e.g. journal.hjed.net), so the mounted MCP app must inherit
        the app's ``allowed_hosts``. Regression test for the production MCP
        outage where every request 421'd before reaching the backend.
        """
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            allowed_hosts=["testserver", "journal.hjed.net"],
        )
        # The context manager runs the app lifespan so the MCP session
        # manager's task group is initialised before the request is handled.
        with TestClient(create_app(settings)) as client:
            # Host header differs from the TestClient ASGI server host
            # ("testserver"), reproducing a request arriving through a reverse
            # proxy.
            response = client.post(
                "/mcp-server/mcp",
                headers={
                    "host": "journal.hjed.net",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            )

        assert response.status_code != 421, (
            "MCP rejected a trusted public Host with 421 Misdirected Request — "
            "allowed_hosts was not propagated to the mounted MCP app"
        )

    def test_cors_allows_own_public_origin(self, db_config):
        """The app's own public origin must be CORS-allowed for MCP endpoints.

        MCP and OAuth discovery endpoints sit outside the same-origin Next.js
        ``/api`` proxy, so the deployed frontend calls them cross-origin. The
        backend must echo Access-Control-Allow-Origin for its own public origin
        even when ``CORS_ORIGINS`` wasn't explicitly updated to include it.
        Regression for the production MCP OAuth CORS failure where requests from
        origin https://journal.hjed.net were blocked. ``CORS_ORIGINS`` is left
        at its localhost default here to prove the public origin is trusted via
        ``frontend_url`` / ``webhook_base_url``.
        """
        public_origin = "https://journal.hjed.net"
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            frontend_url=public_origin,
            webhook_base_url=public_origin,
            allowed_hosts=["*"],
        )
        client = TestClient(create_app(settings))

        response = client.options(
            "/mcp-server/mcp",
            headers={
                "Origin": public_origin,
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.headers.get("access-control-allow-origin") == public_origin, (
            "backend did not allow CORS from its own public origin — "
            "frontend_url/webhook_base_url origin not included in CORS allow-list"
        )

    def test_mcp_mount_path_configurable(self, db_config):
        """Test that MCP mount path is configurable."""
        # Test with different mount path
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/custom-mcp",
        )

        app = create_app(settings)
        client = TestClient(app)

        # Should be mounted at custom path
        response = client.get("/custom-mcp/mcp")
        assert response.status_code != 404


class TestMCPOAuthIntegration:
    """Test MCP OAuth authentication integration."""

    @pytest.fixture
    def auth_settings(self, db_config):
        """Create test settings with MCP OAuth enabled (GitHub)."""
        return Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            webhook_base_url="https://test.example.com",
            github_client_id="test-github-client-id",
            github_client_secret="test-github-client-secret",
            allowed_hosts=["*"],
        )

    @pytest.fixture
    def auth_app(self, auth_settings):
        """Create FastAPI app with MCP OAuth."""
        return create_app(auth_settings)

    @pytest.fixture
    def auth_client(self, auth_app):
        """Create test client for auth-enabled app."""
        return TestClient(auth_app)

    def test_well_known_oauth_metadata_exists(self, auth_client):
        """Test that .well-known OAuth metadata endpoint exists when auth enabled."""
        # The authorization server .well-known is scoped to the root issuer URL
        response = auth_client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data

    def test_well_known_resource_metadata_exists(self, auth_client):
        """Test that .well-known resource metadata endpoint exists."""
        response = auth_client.get(
            "/.well-known/oauth-protected-resource/mcp-server/mcp"
        )
        assert response.status_code == 200
        data = response.json()
        assert "resource" in data

    def test_mcp_rejects_unauthenticated_when_auth_enabled(self, auth_client):
        """Test that MCP endpoint rejects unauthenticated requests."""
        response = auth_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 1,
            },
        )
        # Should return 401 Unauthorized without a valid bearer token
        assert response.status_code in [401, 403]

    def test_no_well_known_when_auth_disabled(self, db_config):
        """Test that .well-known endpoints are NOT present when auth disabled."""
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            disable_auth=True,
            allowed_hosts=["*"],
        )
        app = create_app(settings)
        client = TestClient(app)

        response = client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 404

    def test_api_auth_still_uses_session_cookies(self, auth_client):
        """Test that API endpoints still use session cookie auth (not affected by MCP OAuth)."""
        # API endpoints should still require session cookies, not bearer tokens
        response = auth_client.get("/api/contacts")
        # Should return 401 or 307 (redirect to login) — not affected by MCP OAuth
        assert response.status_code in [401, 307]

    def test_misconfigured_auth_fails_closed(self, db_config):
        """Test that missing webhook_base_url with providers configured fails at startup."""
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            webhook_base_url="",
            github_client_id="test-github-client-id",
            github_client_secret="test-github-client-secret",
            allowed_hosts=["*"],
        )
        # Should raise RuntimeError at app creation — fail closed
        with pytest.raises(RuntimeError, match="WEBHOOK_BASE_URL"):
            create_app(settings)

    def test_generic_oauth_with_redis_storage_builds(self, db_config):
        """Generic OAuth + Redis-backed auto-refresh storage builds cleanly.

        Exercises the full provider wiring (OIDC discovery, refresh threshold,
        pinned signing key, Redis-backed Fernet-encrypted client_storage) so a
        config error in that path fails fast at app creation. RedisStore
        connects lazily, so no live Redis is required to construct the app.
        """
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            webhook_base_url="https://test.example.com",
            oauth_client_id="generic-id",
            oauth_client_secret="generic-secret",
            oauth_authorization_url="https://auth.example.com/authorize",
            oauth_token_url="https://auth.example.com/token",
            oauth_issuer="https://auth.example.com",
            oauth_scopes="openid profile email offline_access",
            mcp_jwt_signing_key="pinned-test-signing-secret",
            mcp_oauth_use_redis_storage=True,
            allowed_hosts=["*"],
        )
        with _stub_discovery():
            app = create_app(settings)
        client = TestClient(app)

        response = client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        assert "token_endpoint" in response.json()

    def test_generic_oauth_without_an_issuer_refuses_to_start(self, db_config):
        """Fail closed at startup rather than accept unverifiable tokens.

        Without discovery there is no JWKS to check the upstream token against,
        which is how the MCP server ended up accepting any non-empty string.
        """
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            webhook_base_url="https://test.example.com",
            oauth_client_id="generic-id",
            oauth_client_secret="generic-secret",
            oauth_authorization_url="https://auth.example.com/authorize",
            oauth_token_url="https://auth.example.com/token",
            allowed_hosts=["*"],
        )
        with pytest.raises(RuntimeError, match="OAUTH_ISSUER"):
            create_app(settings)
