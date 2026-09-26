"""Integration tests for GEAR_USAGE enrichment on the journals API.

These guard the read/write wiring that makes a GEAR_USAGE journal type visible
through the REST API: ``_enrich_journal_data`` must surface the type and its
data, and ``add_type_to_journal`` must create the row from supplied data (and
reject an add with no initial data, since ``gear_item_id`` is required).
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.auth.models import SessionUser


@pytest.fixture
async def gear_item_id(
    async_connection: AsyncConnection, test_user: SessionUser
) -> str:
    gear_id = uuid.uuid4()
    await async_connection.execute(
        text(
            """
            INSERT INTO gear_items (id, user_id, name)
            VALUES (:id, :user_id, 'Test Rope')
            """
        ),
        {"id": str(gear_id), "user_id": test_user.id},
    )
    return str(gear_id)


@pytest.fixture
async def journal_id(async_connection: AsyncConnection, test_user: SessionUser) -> int:
    result = await async_connection.execute(
        text(
            """
            INSERT INTO journals (user_id, title, event_date_range_start, event_date_range_end, content)
            VALUES (:user_id, 'Trip', CURRENT_DATE, CURRENT_DATE, 'A trip')
            RETURNING id
            """
        ),
        {"user_id": test_user.id},
    )
    jid = result.scalar()
    assert jid is not None
    return int(jid)


@pytest.mark.asyncio
async def test_get_journal_surfaces_existing_gear_usage(
    authenticated_client,
    async_connection: AsyncConnection,
    journal_id: int,
    gear_item_id: str,
) -> None:
    """A journal with a gear usage row exposes the type and data via the API."""
    await async_connection.execute(
        text(
            """
            INSERT INTO journal_gear_usage_data (journal_id, gear_item_id)
            VALUES (:journal_id, :gear_item_id)
            """
        ),
        {"journal_id": journal_id, "gear_item_id": gear_item_id},
    )
    await async_connection.execute(
        text(
            """
            INSERT INTO journal_gear_usage_items (journal_id, gear_item_id)
            VALUES (:journal_id, :gear_item_id)
            """
        ),
        {"journal_id": journal_id, "gear_item_id": gear_item_id},
    )

    response = await authenticated_client.get(f"/api/journals/{journal_id}")

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert "gear_usage" in attributes["types"]
    assert attributes["type_data"]["gear_usage"]["gear_item_id"] == gear_item_id


@pytest.mark.asyncio
async def test_add_gear_usage_type_with_data_persists_and_returns(
    authenticated_client,
    journal_id: int,
    gear_item_id: str,
) -> None:
    """Adding GEAR_USAGE with initial data creates the row and returns it."""
    response = await authenticated_client.post(
        f"/api/journals/{journal_id}/types",
        json={
            "data": {
                "type": "journal-type",
                "attributes": {
                    "journal_type": "GEAR_USAGE",
                    "type_data": {"gear_item_id": gear_item_id},
                },
            }
        },
    )

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert "gear_usage" in attributes["types"]
    assert attributes["type_data"]["gear_usage"]["gear_item_id"] == gear_item_id


@pytest.mark.asyncio
async def test_add_gear_usage_type_without_data_is_rejected(
    authenticated_client,
    journal_id: int,
) -> None:
    """GEAR_USAGE requires initial data (gear_item_id) — an empty add fails."""
    response = await authenticated_client.post(
        f"/api/journals/{journal_id}/types",
        json={
            "data": {
                "type": "journal-type",
                "attributes": {"journal_type": "GEAR_USAGE"},
            }
        },
    )

    assert response.status_code == 400
