"""The MCP tools for the addresses an import skipped (#1820)."""

from collections.abc import Callable
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from sqlalchemy.ext.asyncio import AsyncConnection

from app.mcp.domains.integrations.tools import register_integration_tools
from tests.integration.contact_import_issue_seeding import seed_skipped_address
from tests.integration.contact_seeding import OTHER_USER_ID, seed_contact
from tests.integration.mcp.http_helpers import call_mcp_tool, call_mcp_tool_error

pytestmark = pytest.mark.asyncio

LifespanClient = Callable[[], Any]


async def test_import_issue_tools_registered() -> None:
    mcp: FastMCP[None] = FastMCP("TestServer")
    register_integration_tools(mcp)

    async with Client(mcp) as client:
        tool_names = [tool.name for tool in await client.list_tools()]

    assert "list_contact_import_issues" in tool_names
    assert "dismiss_contact_import_issue" in tool_names


async def test_list_contact_import_issues(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    kiri = await seed_contact(async_connection, first_name="Kiri")
    await seed_skipped_address(async_connection, kiri)

    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(
            client, "list_contact_import_issues", {"contact_id": kiri}
        )

    assert "error" not in payload, payload
    [issue] = payload["issues"]
    assert issue["contact_id"] == kiri
    assert issue["reason"] == "unrecognised_region"
    assert issue["address"]["street_line_1"] == "10 Downing St"


async def test_dismiss_contact_import_issue(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    kiri = await seed_contact(async_connection, first_name="Kiri")
    issue_id = await seed_skipped_address(async_connection, kiri)

    async with authenticated_lifespan_client() as client:
        dismissed = await call_mcp_tool(
            client, "dismiss_contact_import_issue", {"issue_id": issue_id}
        )
        listed = await call_mcp_tool(client, "list_contact_import_issues", {})

    assert dismissed["dismissed"] is True
    assert listed["issues"] == []


async def test_dismissing_another_users_issue_is_not_found(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    theirs = await seed_contact(async_connection, user_id=OTHER_USER_ID)
    issue_id = await seed_skipped_address(
        async_connection, theirs, user_id=OTHER_USER_ID
    )

    async with authenticated_lifespan_client() as client:
        error = await call_mcp_tool_error(
            client, "dismiss_contact_import_issue", {"issue_id": issue_id}
        )

    assert "not found" in str(error).lower()


async def test_another_users_contact_lists_what_a_missing_one_does(
    authenticated_lifespan_client: LifespanClient, async_connection: AsyncConnection
) -> None:
    theirs = await seed_contact(async_connection, user_id=OTHER_USER_ID)
    await seed_skipped_address(async_connection, theirs, user_id=OTHER_USER_ID)

    async with authenticated_lifespan_client() as client:
        foreign = await call_mcp_tool(
            client, "list_contact_import_issues", {"contact_id": theirs}
        )
        missing = await call_mcp_tool(
            client, "list_contact_import_issues", {"contact_id": 999_999}
        )

    assert foreign == missing
    assert foreign["issues"] == []
