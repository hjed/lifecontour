"""Integration tests for the contact-suggestion MCP tools.

Exercises ``list_contact_suggestions`` / ``accept_contact_suggestion`` /
``ignore_contact_suggestion`` / ``unignore_contact_suggestion`` over the
mounted MCP HTTP server, with unmatched participant emails seeded on the shared
savepoint connection.
"""

from collections.abc import Callable
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from sqlalchemy.ext.asyncio import AsyncConnection

from app.mcp.domains.integrations.tools import register_integration_tools
from tests.integration.core.integrations.contact_suggestion_seeding import (
    create_contact,
    journal_relationships,
    seed_participant,
)
from tests.integration.mcp.http_helpers import call_mcp_tool

pytestmark = pytest.mark.asyncio

LifespanClient = Callable[[], Any]


async def test_contact_suggestion_tools_registered() -> None:
    mcp: FastMCP[None] = FastMCP("TestServer")
    register_integration_tools(mcp)

    async with Client(mcp) as client:
        tool_names = [tool.name for tool in await client.list_tools()]

    for expected in (
        "list_contact_suggestions",
        "accept_contact_suggestion",
        "ignore_contact_suggestion",
        "unignore_contact_suggestion",
    ):
        assert expected in tool_names, f"Tool {expected} not registered"


async def test_list_contact_suggestions(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    await seed_participant(async_connection, "jane@x.com", 5, display_name="Jane S")

    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(client, "list_contact_suggestions", {})

    assert "error" not in payload, payload
    assert payload["total_count"] == 1
    [suggestion] = payload["suggestions"]
    assert suggestion["email"] == "jane@x.com"
    assert suggestion["display_name"] == "Jane S"
    assert suggestion["event_count"] == 5


async def test_accept_as_new_contact(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    journal_ids = await seed_participant(async_connection, "jane@x.com", 5)

    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(
            client,
            "accept_contact_suggestion",
            {"email": "jane@x.com", "first_name": "Jane", "last_name": "Smith"},
        )

    assert "error" not in payload, payload
    assert payload["linked_journal_count"] == 5
    assert set(
        await journal_relationships(async_connection, payload["contact_id"])
    ) == set(journal_ids)


async def test_accept_into_existing_contact(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    contact_id = await create_contact(async_connection, first_name="Jane")
    await seed_participant(async_connection, "jane@x.com", 5)

    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(
            client,
            "accept_contact_suggestion",
            {"email": "jane@x.com", "contact_id": contact_id},
        )

    assert "error" not in payload, payload
    assert payload["contact_id"] == contact_id


@pytest.mark.parametrize(
    "arguments",
    [
        {"email": "jane@x.com"},
        {"email": "jane@x.com", "contact_id": 1, "first_name": "Jane"},
    ],
    ids=["neither-target", "both-targets"],
)
async def test_accept_needs_exactly_one_target(
    authenticated_lifespan_client: LifespanClient, arguments: dict[str, Any]
) -> None:
    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(client, "accept_contact_suggestion", arguments)

    assert "error" in payload


async def test_accept_into_unknown_contact_is_not_found(
    authenticated_lifespan_client: LifespanClient,
) -> None:
    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(
            client,
            "accept_contact_suggestion",
            {"email": "jane@x.com", "contact_id": 999_999},
        )

    assert "error" in payload


async def test_ignore_and_unignore(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    await seed_participant(async_connection, "noisy@x.com", 5)

    async with authenticated_lifespan_client() as client:
        ignored = await call_mcp_tool(
            client, "ignore_contact_suggestion", {"email": "Noisy@X.com"}
        )
        after_ignore = await call_mcp_tool(
            client, "list_contact_suggestions", {}, request_id=2
        )
        unignored = await call_mcp_tool(
            client,
            "unignore_contact_suggestion",
            {"email": "noisy@x.com"},
            request_id=3,
        )
        after_unignore = await call_mcp_tool(
            client, "list_contact_suggestions", {}, request_id=4
        )

    assert ignored["email"] == "noisy@x.com"
    assert ignored["ignored"] is True
    assert after_ignore["total_count"] == 0
    assert unignored["was_ignored"] is True
    assert after_unignore["total_count"] == 1


async def test_ignore_rejects_a_malformed_email(
    authenticated_lifespan_client: LifespanClient,
) -> None:
    async with authenticated_lifespan_client() as client:
        ignored = await call_mcp_tool(
            client, "ignore_contact_suggestion", {"email": "not-an-email"}
        )
        listed = await call_mcp_tool(
            client, "list_contact_suggestions", {}, request_id=2
        )

    assert "error" in ignored
    assert listed["ignored_emails"] == []
