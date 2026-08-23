"""The dev/test OAuth client must register the callback FastMCP actually serves.

``docker/oauth-provider/init-oauth.sh`` bootstraps the Hydra client every local
stack authenticates against. FastMCP's OAuth proxy serves its own callback at
``{WEBHOOK_BASE_URL}{MCP_MOUNT_PATH}/auth/callback``, so a client registered
without that URI has Hydra reject the MCP flow at the authorize step — before it
starts, and with nothing on the backend to log.

These tests derive the expected URI from the *real* proxy rather than restating
it, so the registration cannot drift from the address the backend listens on.
The script is invoked in its ``--print-redirect-uris`` mode, which prints the
list it would register and exits without contacting Hydra.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration

from app.infrastructure.config import Settings
from app.mcp.auth.providers import McpOidcProxy, create_mcp_auth_provider

REPO_ROOT = Path(__file__).resolve().parents[5]
INIT_OAUTH_SCRIPT = REPO_ROOT / "docker" / "oauth-provider" / "init-oauth.sh"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

# The compose defaults the dev stack runs on when nothing overrides them.
DEV_FRONTEND_URL = "http://localhost:3000"
DEV_BACKEND_URL = "http://localhost:8000"
DEV_MOUNT_PATH = "/mcp-server"

_DISCOVERY_DOCUMENT: dict[str, object] = {
    "issuer": "http://localhost:4444",
    "authorization_endpoint": "http://localhost:4444/oauth2/auth",
    "token_endpoint": "http://localhost:4444/oauth2/token",
    "jwks_uri": "http://localhost:4444/.well-known/jwks.json",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
}


def _proxy_callback(*, backend_url: str, mount_path: str) -> str:
    """The redirect URI the MCP OAuth proxy hands the upstream IdP.

    Built by standing up the real provider, so this tracks whatever FastMCP
    decides its callback path is rather than hard-coding ``/auth/callback``.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/test",
        webhook_base_url=backend_url,
        mcp_mount_path=mount_path,
        oauth_client_id="dev-client-id",
        oauth_client_secret="dev-client-secret",
        oauth_issuer="http://localhost:4444",
        mcp_oauth_use_redis_storage=False,
        disable_auth=False,
    )
    with patch.object(
        OIDCConfiguration,
        "get_oidc_configuration",
        return_value=OIDCConfiguration.model_validate(_DISCOVERY_DOCUMENT),
    ):
        provider = create_mcp_auth_provider(settings)
    assert isinstance(provider, McpOidcProxy)
    return f"{str(provider.base_url).rstrip('/')}{provider._redirect_path}"


def _registered_redirect_uris(**env: str) -> list[str]:
    """The redirect URIs ``init-oauth.sh`` would register under this env."""
    result = subprocess.run(
        ["sh", str(INIT_OAUTH_SCRIPT), "--print-redirect-uris"],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **env},
    )
    uris = json.loads(result.stdout)
    assert isinstance(uris, list)
    return uris


def _compose_service_environment(service: str) -> dict[str, str]:
    """A compose service's ``environment:`` block, list or map form alike."""
    with COMPOSE_FILE.open() as handle:
        compose: dict[str, Any] = yaml.safe_load(handle)
    environment = compose["services"][service]["environment"]
    if isinstance(environment, dict):
        return {key: str(value) for key, value in environment.items()}
    return dict(entry.split("=", 1) for entry in environment)


def _env_file(name: str) -> dict[str, str]:
    """The assignments in a repo-root env file, comments and blanks skipped."""
    values: dict[str, str] = {}
    for line in (REPO_ROOT / name).read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


class TestMcpCallbackRegistration:
    """The MCP callback is registered, and derived from the same variables."""

    def test_registers_the_callback_the_proxy_actually_serves(self) -> None:
        uris = _registered_redirect_uris(
            FRONTEND_URL=DEV_FRONTEND_URL,
            WEBHOOK_BASE_URL=DEV_BACKEND_URL,
            MCP_MOUNT_PATH=DEV_MOUNT_PATH,
        )
        assert (
            _proxy_callback(backend_url=DEV_BACKEND_URL, mount_path=DEV_MOUNT_PATH)
            in uris
        )

    def test_follows_the_backend_url_and_mount_path_it_is_given(self) -> None:
        """The E2E stack publishes the backend on a workspace-derived port."""
        backend_url = "http://localhost:8011"
        mount_path = "/custom-mcp"
        uris = _registered_redirect_uris(
            FRONTEND_URL="http://localhost:3110",
            WEBHOOK_BASE_URL=backend_url,
            MCP_MOUNT_PATH=mount_path,
        )
        assert _proxy_callback(backend_url=backend_url, mount_path=mount_path) in uris

    def test_still_registers_the_web_app_callback(self) -> None:
        """The browser login flow must keep working alongside MCP."""
        uris = _registered_redirect_uris(
            FRONTEND_URL="http://localhost:3110",
            WEBHOOK_BASE_URL=DEV_BACKEND_URL,
            MCP_MOUNT_PATH=DEV_MOUNT_PATH,
        )
        assert "http://localhost:3110/auth/callback" in uris

    def test_defaults_match_the_dev_stack_when_nothing_is_exported(self) -> None:
        """A bare `docker compose --profile dev up` gets both callbacks."""
        assert sorted(_registered_redirect_uris()) == sorted(
            [
                f"{DEV_FRONTEND_URL}/auth/callback",
                f"{DEV_BACKEND_URL}{DEV_MOUNT_PATH}/auth/callback",
            ]
        )


class TestComposeWiring:
    """oauth-init and the backend must read one source for these values."""

    @pytest.mark.parametrize("variable", ["WEBHOOK_BASE_URL", "MCP_MOUNT_PATH"])
    def test_oauth_init_and_backend_are_given_the_same_expression(
        self, variable: str
    ) -> None:
        oauth_init = _compose_service_environment("oauth-init")
        backend = _compose_service_environment("backend")
        assert variable in oauth_init, (
            f"{variable} is not passed to oauth-init, so the registered "
            "redirect URI cannot follow the backend's own base URL"
        )
        assert variable in backend, (
            f"{variable} is not passed to the backend, so it would keep its "
            "built-in default while oauth-init registered something else"
        )
        assert oauth_init[variable] == backend[variable]

    def test_the_test_env_file_points_at_its_own_published_port(self) -> None:
        """CI brings the stack up straight from .env.test, without global-setup.

        A WEBHOOK_BASE_URL on a different port than the one the backend is
        published on registers a callback nothing can reach.
        """
        env = _env_file(".env.test")
        assert env["WEBHOOK_BASE_URL"] == f"http://localhost:{env['BACKEND_PORT']}"
