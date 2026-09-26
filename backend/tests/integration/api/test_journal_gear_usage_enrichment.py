"""Integration tests for GEAR_USAGE enrichment on the journals API.

These guard the read/write wiring that makes a GEAR_USAGE journal type visible
through the REST API: ``_enrich_journal_data`` must surface the type and its
data, and ``add_type_to_journal`` must create the row from supplied data (and
reject an add with no initial data, since ``gear_item_id`` is required).
"""

import uuid

import pytest
from httpx import AsyncClient
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


@pytest.fixture
async def more_gear_item_ids(
    async_connection: AsyncConnection, test_user: SessionUser
) -> list[str]:
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for gear_id, name in zip(ids, ("Harness", "Helmet"), strict=True):
        await async_connection.execute(
            text(
                "INSERT INTO gear_items (id, user_id, name) VALUES (:id, :user_id, :name)"
            ),
            {"id": gear_id, "user_id": test_user.id, "name": name},
        )
    return ids


async def _put_gear_usage(
    client: AsyncClient, journal_id: int, attributes: dict[str, object]
) -> dict[str, object]:
    response = await client.put(
        f"/api/journals/{journal_id}/types/GEAR_USAGE/data",
        json={"data": {"type": "journal-type-data", "attributes": attributes}},
    )
    assert response.status_code == 200, response.text
    gear_usage: dict[str, object] = response.json()["data"]["attributes"]["type_data"][
        "gear_usage"
    ]
    return gear_usage


def _gear_ids(gear_usage: dict[str, object]) -> list[str]:
    items = gear_usage["items"]
    assert isinstance(items, list)
    return [item["gear_item_id"] for item in items]


async def _journal_updated_events(connection: AsyncConnection, journal_id: int) -> int:
    result = await connection.execute(
        text(
            "SELECT count(*) FROM outbox_events "
            "WHERE event_type = 'JournalUpdated' AND aggregate_id = :id"
        ),
        {"id": journal_id},
    )
    return int(result.scalar() or 0)


@pytest.mark.asyncio
async def test_a_journal_records_several_gear_items(
    authenticated_client: AsyncClient,
    journal_id: int,
    gear_item_id: str,
    more_gear_item_ids: list[str],
) -> None:
    """Items are added, listed in order, and a second never replaces the first."""
    harness, helmet = more_gear_item_ids
    add = await authenticated_client.post(
        f"/api/journals/{journal_id}/types",
        json={
            "data": {
                "type": "journal-type",
                "attributes": {
                    "journal_type": "GEAR_USAGE",
                    "type_data": {
                        "items": [
                            {"gear_item_id": gear_item_id},
                            {
                                "gear_item_id": harness,
                                "checkout_date": "2024-01-14T20:00:00+00:00",
                            },
                        ]
                    },
                },
            }
        },
    )
    assert add.status_code == 200, add.text
    gear_usage = add.json()["data"]["attributes"]["type_data"]["gear_usage"]
    assert _gear_ids(gear_usage) == [gear_item_id, harness]
    # The single-item fields still carry the first item for older readers.
    assert gear_usage["gear_item_id"] == gear_item_id

    # The older single-item form adds a third item and keeps the others.
    gear_usage = await _put_gear_usage(
        authenticated_client, journal_id, {"gear_item_id": helmet}
    )
    assert _gear_ids(gear_usage) == [gear_item_id, harness, helmet]

    # The list replaces the whole set: leaving the harness out removes it.
    gear_usage = await _put_gear_usage(
        authenticated_client,
        journal_id,
        {"items": [{"gear_item_id": gear_item_id}, {"gear_item_id": helmet}]},
    )
    assert _gear_ids(gear_usage) == [gear_item_id, helmet]

    fetched = await authenticated_client.get(f"/api/journals/{journal_id}")
    items = fetched.json()["data"]["attributes"]["type_data"]["gear_usage"]["items"]
    assert [item["gear_item_id"] for item in items] == [gear_item_id, helmet]


@pytest.mark.asyncio
async def test_adding_and_removing_the_type_tells_integrations(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    journal_id: int,
    gear_item_id: str,
) -> None:
    """Snipe-IT acts on JournalUpdated, so the type's add and remove publish it."""
    before = await _journal_updated_events(async_connection, journal_id)

    add = await authenticated_client.post(
        f"/api/journals/{journal_id}/types",
        json={
            "data": {
                "type": "journal-type",
                "attributes": {
                    "journal_type": "GEAR_USAGE",
                    "type_data": {"items": [{"gear_item_id": gear_item_id}]},
                },
            }
        },
    )
    assert add.status_code == 200, add.text
    assert await _journal_updated_events(async_connection, journal_id) == before + 1

    removed = await authenticated_client.delete(
        f"/api/journals/{journal_id}/types/GEAR_USAGE"
    )
    assert removed.status_code == 200, removed.text
    assert await _journal_updated_events(async_connection, journal_id) == before + 2


@pytest.mark.asyncio
async def test_adding_the_type_with_no_gear_item_is_rejected(
    authenticated_client: AsyncClient,
    journal_id: int,
) -> None:
    response = await authenticated_client.post(
        f"/api/journals/{journal_id}/types",
        json={
            "data": {
                "type": "journal-type",
                "attributes": {
                    "journal_type": "GEAR_USAGE",
                    "type_data": {"items": []},
                },
            }
        },
    )

    assert response.status_code == 400
