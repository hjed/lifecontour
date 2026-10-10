"""MCP tools that create a contact make it the acting user's.

``create_contact`` and ``resolve_immich_conflict(action="create")`` each build
a new contact; both stamp the MCP request's user as its owner, and the Immich
link the conflict writes is the acting user's too, beside any link another
user holds for the same person.
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


async def _seed_conflict(conn: AsyncConnection, person_id: str) -> int:
    conflict_id: int = (
        await conn.execute(
            text("""
                INSERT INTO pending_entity_mappings
                    (user_id, integration_source, external_entity_id,
                     external_entity_name, candidate_contact_ids, status)
                VALUES (:user_id, 'immich', :person_id, 'Ada Lovelace',
                        '[]'::jsonb, 'unresolved')
                RETURNING id
            """),
            {"user_id": TEST_USER_ID, "person_id": person_id},
        )
    ).scalar_one()
    return conflict_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolving_an_immich_conflict_stamps_the_link_owner(
    authenticated_lifespan_client: Callable[..., Any],
    async_connection: AsyncConnection,
) -> None:
    conflict_id = await _seed_conflict(async_connection, "person-link-owned")

    async with authenticated_lifespan_client() as client:
        await call_mcp_tool(
            client,
            "resolve_immich_conflict",
            {"conflict_id": conflict_id, "action": "create"},
        )

    owner = (
        await async_connection.execute(
            text(
                "SELECT user_id FROM sync_metadata "
                "WHERE external_id = 'person-link-owned'"
            )
        )
    ).scalar_one()
    assert owner == TEST_USER_ID


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolving_a_conflict_for_a_person_another_user_links(
    authenticated_lifespan_client: Callable[..., Any],
    async_connection: AsyncConnection,
) -> None:
    """Another user's link for the same Immich person is theirs; this user's
    new contact gets its own link beside it."""
    conflict_id = await _seed_conflict(async_connection, "person-shared")
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 last_synced_at, version_hash, sync_status, internal_entity_type)
            VALUES ('other-user-456', 999, 'immich', 'person-shared',
                    now(), 'theirs', 'success', 'contact')
        """)
    )

    async with authenticated_lifespan_client() as client:
        await call_mcp_tool(
            client,
            "resolve_immich_conflict",
            {"conflict_id": conflict_id, "action": "create"},
        )

    links = (
        await async_connection.execute(
            text(
                "SELECT user_id, internal_id FROM sync_metadata "
                "WHERE external_id = 'person-shared' ORDER BY user_id"
            )
        )
    ).fetchall()
    assert len(links) == 2
    (other_owner, other_contact), (owner, contact_id) = (tuple(r) for r in links)
    assert (other_owner, other_contact) == ("other-user-456", 999)
    assert owner == TEST_USER_ID
    assert await _owner(async_connection, contact_id) == TEST_USER_ID
