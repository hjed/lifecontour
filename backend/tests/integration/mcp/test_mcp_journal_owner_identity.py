"""A journal created over MCP must belong to the person who authenticated.

Under the generic-OAuth proxy the acting user comes from the verified upstream
``id_token``: its ``sub`` names the person who logged in. The failure this
guards against is the token arriving with no identity at all, where the acting
user fell through to the OAuth ``client_id`` — so every MCP write landed on a
phantom owner, invisible to the signed-in user, whose owner-scoped REST reads
then answered 404 (the original symptom, on the activity feed).

These tests drive the real token path rather than the DI fallback the other MCP
integration tests use, because the DI fallback resolves the same ``SessionUser``
for MCP and REST and so cannot reproduce the split.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)

# The OAuth client the request arrived through. It names the application, never
# the person — pinned here so the regression is visible if the fallback to it is
# ever reintroduced.
OAUTH_CLIENT_ID = "generic-id"


@pytest.fixture
def oauth_authenticated_mcp(test_user: Any) -> Callable[..., Any]:
    """Present the MCP server an OAuth token shaped like the prod one.

    The claims are those of a verified upstream ``id_token``; ``sub=None``
    models a token that carries no identity, which must not authenticate.
    """

    @asynccontextmanager
    async def _acting_as(sub: str | None = None) -> AsyncGenerator[None]:
        token = MagicMock()
        token.client_id = OAUTH_CLIENT_ID
        claims: dict[str, Any] = {"aud": OAUTH_CLIENT_ID}
        if sub is not None:
            claims |= {
                "sub": sub,
                "email": test_user.email,
                "name": test_user.name,
            }
        token.claims = claims
        with patch(
            "fastmcp.server.dependencies.get_access_token",
            return_value=token,
        ):
            yield

    return _acting_as


async def _create_journal_via_mcp(client: Any, title: str) -> dict[str, Any]:
    return await call_mcp_tool(
        client,
        "create_journal_entry",
        {
            "request": {
                "title": title,
                "content": "Created through MCP.",
                "event_date_range": {
                    "start": "2025-10-02",
                    "end": "2025-10-18",
                },
                "types": ["NOTE"],
            }
        },
        request_id=2,
    )


async def _owner_of(connection: AsyncConnection, journal_id: int) -> str | None:
    row = (
        await connection.execute(
            text("SELECT user_id FROM journals WHERE id = :id"),
            {"id": journal_id},
        )
    ).fetchone()
    return None if row is None else str(row.user_id)


class TestMCPWritesBelongToTheAuthenticatedUser:
    async def test_created_journal_is_owned_by_the_upstream_subject(
        self,
        authenticated_lifespan_client: Any,
        async_connection: AsyncConnection,
        oauth_authenticated_mcp: Callable[..., Any],
        test_user: Any,
    ) -> None:
        async with oauth_authenticated_mcp(test_user.id):
            async with authenticated_lifespan_client() as client:
                payload = await _create_journal_via_mcp(
                    client, "Owned by the signed-in user"
                )

        assert "error" not in payload, f"Unexpected error: {payload}"
        owner = await _owner_of(async_connection, int(payload["id"]))
        assert owner == test_user.id
        assert owner != OAUTH_CLIENT_ID

    async def test_created_journal_is_readable_over_the_rest_api(
        self,
        authenticated_lifespan_client: Any,
        authenticated_client: Any,
        oauth_authenticated_mcp: Callable[..., Any],
        test_user: Any,
    ) -> None:
        """The ticket, end to end: detail *and* the activity feed must load."""
        async with oauth_authenticated_mcp(test_user.id):
            async with authenticated_lifespan_client() as client:
                payload = await _create_journal_via_mcp(
                    client, "Readable in the web UI"
                )

        journal_id = int(payload["id"])

        detail = await authenticated_client.get(f"/api/journals/{journal_id}")
        assert detail.status_code == 200

        history = await authenticated_client.get(f"/api/journals/{journal_id}/history")
        assert history.status_code == 200, (
            "The activity feed 404s when the journal is owned by someone other "
            "than the signed-in user"
        )

    async def test_token_without_an_identity_claim_is_refused(
        self,
        authenticated_lifespan_client: Any,
        oauth_authenticated_mcp: Callable[..., Any],
    ) -> None:
        """No identity must fail, not silently resolve to the client id."""
        async with oauth_authenticated_mcp(None):
            async with authenticated_lifespan_client() as client:
                payload = await _create_journal_via_mcp(
                    client, "Should never be created"
                )

        assert "error" in payload, (
            f"A claimless token must not authenticate; got: {payload}"
        )


# "debug-client" was FastMCP's DebugTokenVerifier default and is what the
# synthetic-owner migration reassigns; "dev-user" is the auth-disabled fallback.
@pytest.mark.parametrize(
    "synthetic_owner", ["debug-client", "dev-user", OAUTH_CLIENT_ID]
)
async def test_synthetic_owners_are_never_the_acting_user(
    authenticated_lifespan_client: Any,
    async_connection: AsyncConnection,
    oauth_authenticated_mcp: Callable[..., Any],
    test_user: Any,
    synthetic_owner: str,
) -> None:
    """No stand-in identity may end up owning an MCP-created journal."""
    async with oauth_authenticated_mcp(test_user.id):
        async with authenticated_lifespan_client() as client:
            payload = await _create_journal_via_mcp(
                client, f"Not owned by {synthetic_owner}"
            )

    owner = await _owner_of(async_connection, int(payload["id"]))
    assert owner != synthetic_owner
