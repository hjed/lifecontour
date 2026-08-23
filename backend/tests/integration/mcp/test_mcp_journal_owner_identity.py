"""A journal created over MCP must belong to the person who authenticated.

Under the generic-OAuth proxy the verified ``AccessToken`` comes from
``DebugTokenVerifier``: ``claims={"token": <raw upstream token>}`` and the
verifier's hard-coded ``client_id`` default. With no identity claim of its own,
the acting user fell through to that ``client_id``, so every MCP write was
attributed to a phantom owner — invisible to the signed-in user, whose
owner-scoped REST reads then answered 404 (this ticket's symptom, on the
activity feed).

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
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)

# The verifier's default client id. Never a user identity — pinned here so the
# regression is visible if the fallback is ever reintroduced.
DEBUG_CLIENT_ID = "debug-client"


@pytest.fixture
def oauth_authenticated_mcp(test_user: Any) -> Callable[..., Any]:
    """Present the MCP server an OAuth token shaped like the prod one.

    Identity lives only in ``upstream_claims`` — the flat claims carry the raw
    upstream token, exactly as ``DebugTokenVerifier`` returns it.
    """

    @asynccontextmanager
    async def _acting_as(sub: str | None = None) -> AsyncGenerator[None]:
        token = MagicMock()
        token.client_id = DEBUG_CLIENT_ID
        token.claims = {"token": "opaque-upstream-token"}
        if sub is not None:
            token.claims["upstream_claims"] = {
                "sub": sub,
                "email": test_user.email,
                "name": test_user.name,
            }
        with patch(
            "fastmcp.server.dependencies.get_access_token",
            return_value=token,
        ):
            yield

    return _acting_as


async def _create_journal_via_mcp(
    client: Any, session_id: str, title: str
) -> dict[str, Any]:
    response = await client.post(
        "/mcp-server/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "create_journal_entry",
                "arguments": {
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
            },
        },
        headers=mcp_headers(session_id),
    )
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


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
                session_id = await initialize_mcp_session(client)
                payload = await _create_journal_via_mcp(
                    client, session_id, "Owned by the signed-in user"
                )

        assert "error" not in payload, f"Unexpected error: {payload}"
        owner = await _owner_of(async_connection, int(payload["id"]))
        assert owner == test_user.id
        assert owner != DEBUG_CLIENT_ID

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
                session_id = await initialize_mcp_session(client)
                payload = await _create_journal_via_mcp(
                    client, session_id, "Readable in the web UI"
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
                session_id = await initialize_mcp_session(client)
                payload = await _create_journal_via_mcp(
                    client, session_id, "Should never be created"
                )

        assert "error" in payload, (
            f"A claimless token must not authenticate; got: {payload}"
        )


@pytest.mark.parametrize("synthetic_owner", [DEBUG_CLIENT_ID, "dev-user"])
async def test_synthetic_owners_are_never_the_acting_user(
    authenticated_lifespan_client: Any,
    async_connection: AsyncConnection,
    oauth_authenticated_mcp: Callable[..., Any],
    test_user: Any,
    synthetic_owner: str,
) -> None:
    """Neither hard-coded constant may end up owning an MCP-created journal."""
    async with oauth_authenticated_mcp(test_user.id):
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_journal_via_mcp(
                client, session_id, f"Not owned by {synthetic_owner}"
            )

    owner = await _owner_of(async_connection, int(payload["id"]))
    assert owner != synthetic_owner
