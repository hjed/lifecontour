"""Tests for the integration suite's own speed-ups.

- The suite shares one FastMCP server between every app it mounts, because
  building one registers every tool and generates its JSON schemas, which used
  to be most of each API and MCP test's setup. These tests pin what may and may
  not share it.
"""

import copy
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from fastmcp import FastMCP
from starlette.applications import Starlette

from app.infrastructure.config import Settings
from app.main import create_app
from app.mcp.shared.read_only_tools import create_read_only_mcp_server
from tests.integration.mcp.http_helpers import call_mcp_tool

LifespanClientFactory = Callable[[], AbstractAsyncContextManager[Any]]


def _mounted_mcp_server(app: Any) -> FastMCP[None]:
    mcp_app = cast(Starlette, app.state.mcp_app)
    return cast(FastMCP[None], mcp_app.state.fastmcp_server)


@pytest.fixture
def unauthenticated_settings(test_settings: Settings) -> Settings:
    """Settings that build no MCP auth provider, whatever ``.env`` configures.

    ``test_settings`` takes every field it does not name from the environment,
    so local OAuth credentials would otherwise give these apps an auth
    provider, and with it a server of their own.
    """
    return test_settings.model_copy(update={"disable_auth": True})


@pytest.fixture
def oauth_settings(test_settings: Settings) -> Settings:
    """Settings that always build an MCP auth provider (GitHub OAuth)."""
    return test_settings.model_copy(
        update={
            "disable_auth": False,
            "webhook_base_url": "https://test.example.com",
            "github_client_id": "test-github-client-id",
            "github_client_secret": "test-github-client-secret",
        }
    )


@pytest.mark.integration
class TestSharedMcpServer:
    """Mounted apps share one server; nothing else does."""

    def test_two_apps_mount_the_same_server_on_their_own_asgi_apps(
        self, unauthenticated_settings: Settings
    ) -> None:
        first = create_app(settings=unauthenticated_settings)
        second = create_app(settings=unauthenticated_settings)

        assert _mounted_mcp_server(first) is _mounted_mcp_server(second)
        assert first.state.mcp_app is not second.state.mcp_app

    def test_an_app_with_an_auth_provider_builds_its_own_server(
        self, unauthenticated_settings: Settings, oauth_settings: Settings
    ) -> None:
        shared = _mounted_mcp_server(create_app(settings=unauthenticated_settings))

        authed = _mounted_mcp_server(create_app(settings=oauth_settings))

        assert authed.auth is not None
        assert authed is not shared

    async def test_building_the_read_only_server_leaves_the_shared_schemas_alone(
        self, unauthenticated_settings: Settings
    ) -> None:
        """The read-only server sanitises its tools' schemas in place.

        It must do that to a server of its own: were it handed the shared one,
        every later test would see the sanitised schemas.
        """
        shared = _mounted_mcp_server(create_app(settings=unauthenticated_settings))
        tool = await shared.get_tool("search_journals")
        assert tool is not None
        before = copy.deepcopy(tool.parameters)

        await create_read_only_mcp_server()

        assert tool.parameters == before

    async def test_the_shared_server_serves_one_lifespan_after_another(
        self, authenticated_lifespan_client: LifespanClientFactory
    ) -> None:
        for _ in range(2):
            async with authenticated_lifespan_client() as client:
                payload = await call_mcp_tool(client, "list_journal_types", {})
                assert payload["journal_types"]
