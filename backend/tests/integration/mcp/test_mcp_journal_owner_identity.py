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

from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag
from tests.integration.contact_seeding import OTHER_USER_ID
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
    post_mcp_tool,
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


# Another user's journal tag, by a name the acting user could plausibly use too.
THEIR_TAG = "their-family"


async def _their_tag(connection: AsyncConnection) -> JournalTag:
    tag = await SqlJournalTagRepository(connection).save(
        JournalTag(user_id=OTHER_USER_ID, name=THEIR_TAG, color="#123456")
    )
    assert tag.id is not None
    return tag


async def _tag_row(connection: AsyncConnection, tag: JournalTag) -> str | None:
    row = (
        await connection.execute(
            text("SELECT to_jsonb(t)::text FROM journal_tags t WHERE id = :id"),
            {"id": tag.id},
        )
    ).fetchone()
    return None if row is None else str(row[0])


class TestMCPJournalTagsAreTheAuthenticatedUsers:
    """The journal tag tools see and change only the acting user's tags."""

    async def test_listing_shows_only_your_tags(
        self,
        authenticated_lifespan_client: Any,
        async_connection: AsyncConnection,
        oauth_authenticated_mcp: Callable[..., Any],
        test_user: Any,
    ) -> None:
        await _their_tag(async_connection)
        await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=test_user.id, name="mine")
        )

        async with oauth_authenticated_mcp(test_user.id):
            async with authenticated_lifespan_client() as client:
                payload = await call_mcp_tool(client, "list_journal_tags", {})

        assert [tag["name"] for tag in payload["tags"]] == ["mine"]

    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            # "{theirs}" / "{mine}" name the seeded tags, filled in below.
            (
                "update_journal_tag",
                {"tag_id": "{theirs}", "name": "renamed-by-a-stranger"},
            ),
            ("delete_journal_tag", {"tag_id": "{theirs}"}),
            (
                "merge_journal_tag",
                {"source_tag_id": "{theirs}", "target_tag_id": "{mine}"},
            ),
        ],
    )
    async def test_their_tag_is_not_found_and_left_unchanged(
        self,
        authenticated_lifespan_client: Any,
        async_connection: AsyncConnection,
        oauth_authenticated_mcp: Callable[..., Any],
        test_user: Any,
        tool: str,
        arguments: dict[str, Any],
    ) -> None:
        theirs = await _their_tag(async_connection)
        mine = await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=test_user.id, name="mine")
        )
        before = await _tag_row(async_connection, theirs)
        arguments = {
            name: value.format(theirs=theirs.id, mine=mine.id)
            for name, value in arguments.items()
        }

        async with oauth_authenticated_mcp(test_user.id):
            async with authenticated_lifespan_client() as client:
                response = await post_mcp_tool(client, tool, arguments, request_id=2)

        assert response.status_code == 200
        assert "not found" in response.text.lower()
        assert THEIR_TAG not in response.text
        assert await _tag_row(async_connection, theirs) == before

    async def test_a_journal_tag_name_resolves_to_your_own_tag(
        self,
        authenticated_lifespan_client: Any,
        async_connection: AsyncConnection,
        oauth_authenticated_mcp: Callable[..., Any],
        test_user: Any,
    ) -> None:
        """Naming a tag another user holds creates yours rather than using theirs."""
        theirs = await _their_tag(async_connection)

        async with oauth_authenticated_mcp(test_user.id):
            async with authenticated_lifespan_client() as client:
                payload = await call_mcp_tool(
                    client,
                    "create_journal_entry",
                    {
                        "request": {
                            "title": "Tagged by name",
                            "content": "Created through MCP.",
                            "event_date_range": {
                                "start": "2025-10-02",
                                "end": "2025-10-18",
                            },
                            "types": ["NOTE"],
                            "tags": [THEIR_TAG],
                        }
                    },
                    request_id=2,
                )

        assert "error" not in payload, payload
        owners = (
            await async_connection.execute(
                text(
                    """
                    SELECT t.id, t.user_id FROM journal_tag_assignments a
                    JOIN journal_tags t ON t.id = a.tag_id
                    WHERE a.journal_id = :id
                    """
                ),
                {"id": int(payload["id"])},
            )
        ).fetchall()
        assert [(row.user_id, row.id == theirs.id) for row in owners] == [
            (test_user.id, False)
        ]

    async def test_searching_by_their_tag_name_finds_no_tag(
        self,
        authenticated_lifespan_client: Any,
        async_connection: AsyncConnection,
        oauth_authenticated_mcp: Callable[..., Any],
        test_user: Any,
    ) -> None:
        """Their tag name is unknown to you, so the filter is refused, not widened."""
        await _their_tag(async_connection)

        async with oauth_authenticated_mcp(test_user.id):
            async with authenticated_lifespan_client() as client:
                response = await post_mcp_tool(
                    client, "search_journals", {"tags": THEIR_TAG}, request_id=2
                )

        assert response.status_code == 200
        assert "unknown journal tag" in response.text.lower()
