"""MCP tools that create a contact make it the acting user's.

``create_contact`` and ``resolve_immich_conflict(action="create")`` each build
a new contact; both stamp the MCP request's user as its owner.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.mcp.http_helpers import call_mcp_tool


async def _owner(conn: AsyncConnection, contact_id: int) -> str | None:
    result = await conn.execute(
        text("SELECT user_id FROM contacts WHERE id = :id"), {"id": contact_id}
    )
    owner: str | None = result.scalar_one()
    return owner


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_contact_is_owned_by_the_acting_user(
    authenticated_lifespan_client: Callable[..., Any],
    async_connection: AsyncConnection,
) -> None:
    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(
            client, "create_contact", {"request": {"first_name": "Owned"}}
        )

    assert await _owner(async_connection, int(payload["id"])) == TEST_USER_ID


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolving_an_immich_conflict_by_creating_owns_the_contact(
    authenticated_lifespan_client: Callable[..., Any],
    async_connection: AsyncConnection,
) -> None:
    conflict_id = (
        await async_connection.execute(
            text("""
                INSERT INTO pending_entity_mappings
                    (user_id, integration_source, external_entity_id,
                     external_entity_name, candidate_contact_ids, status)
                VALUES (:user_id, 'immich', 'person-owned', 'Ada Lovelace',
                        '[]'::jsonb, 'unresolved')
                RETURNING id
            """),
            {"user_id": TEST_USER_ID},
        )
    ).scalar_one()

    async with authenticated_lifespan_client() as client:
        await call_mcp_tool(
            client,
            "resolve_immich_conflict",
            {"conflict_id": conflict_id, "action": "create"},
        )

    contact_id = (
        await async_connection.execute(
            text(
                "SELECT resolved_contact_id FROM pending_entity_mappings WHERE id = :id"
            ),
            {"id": conflict_id},
        )
    ).scalar_one()
    assert await _owner(async_connection, contact_id) == TEST_USER_ID
