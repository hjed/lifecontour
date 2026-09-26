import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.infrastructure.auth.models import SessionUser

_SNIPEIT_MAINTENANCE_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"
_MAINTENANCE_SOURCE = "snipeit_maintenance"
# The record journal 215032 was imported from, and the echo its old push created
_ORIGINAL = "snipeit_maint:17"
_ECHO = "snipeit_maint:20"


async def _journal(connection: AsyncConnection, user_id: str) -> int:
    result = await connection.execute(
        text(
            """
            INSERT INTO journals (user_id, event_date_range_start, event_date_range_end, title, content)
            VALUES (:user_id, CURRENT_DATE, CURRENT_DATE, 'Maintenance', 'Imported')
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    journal_id = result.scalar()
    assert journal_id is not None
    return int(journal_id)


async def _link_import(
    connection: AsyncConnection, user_id: str, journal_id: int, external_id: str
) -> None:
    """Link a journal to the record it was imported from, as the backend does."""
    await connection.execute(
        text(
            """
            INSERT INTO calendars (id, user_id, name, color, integration_source)
            VALUES (:id, :user_id, 'Snipeit_Maintenance Calendar', '#808080',
                    'snipeit_maintenance')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": _SNIPEIT_MAINTENANCE_CALENDAR_ID, "user_id": user_id},
    )
    await connection.execute(
        text(
            """
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, sync_capability, sync_status)
            VALUES (:journal_id, :calendar_id, :external_id, 'bidirectional', 'synced')
            """
        ),
        {
            "journal_id": journal_id,
            "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
            "external_id": external_id,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO sync_metadata (integration_source, external_id, sync_status, version_hash, last_synced_at)
            VALUES ('snipeit_maintenance', :external_id, 'success', 'import-hash', CURRENT_TIMESTAMP)
            """
        ),
        {"external_id": external_id},
    )


async def _record_push(
    connection: AsyncConnection, journal_id: int, external_id: str
) -> None:
    """A push row naming the journal, as a (pre-#1468) echo push left it."""
    await connection.execute(
        text(
            """
            INSERT INTO sync_metadata (integration_source, external_id, internal_uuid, sync_status, version_hash, last_synced_at)
            VALUES ('snipeit_maintenance', :external_id, :journal_id, 'success', 'push-hash', CURRENT_TIMESTAMP)
            """
        ),
        {"external_id": external_id, "journal_id": str(journal_id)},
    )


async def _snipeit_settings(connection: AsyncConnection, user_id: str) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO snipeit_settings (user_id, base_url, snipeit_user_id, webhook_token)
            VALUES (:user_id, 'https://snipeit.example.com', '123', :webhook_token)
            """
        ),
        {"user_id": user_id, "webhook_token": f"webhook-token-{user_id}"},
    )


@pytest.fixture
async def journal_with_snipeit_links(
    async_connection: AsyncConnection, test_user: SessionUser
) -> int:
    # 1. Create a basic journal
    result = await async_connection.execute(
        text(
            """
            INSERT INTO journals (user_id, event_date_range_start, event_date_range_end, title, content)
            VALUES (:user_id, CURRENT_DATE, CURRENT_DATE, 'Maintenance', 'Testing maint')
            RETURNING id
            """
        ),
        {"user_id": test_user.id},
    )
    journal_id = result.scalar()

    # 2. Add Snipe-IT Settings
    await _snipeit_settings(async_connection, test_user.id)

    await async_connection.execute(
        text(
            """
            INSERT INTO sync_metadata (integration_source, external_id, internal_uuid, sync_status, version_hash, last_synced_at)
            VALUES ('snipeit_maintenance', 'snipeit_maint:42', :journal_id, 'success', 'hash1', CURRENT_TIMESTAMP)
            """
        ),
        {"journal_id": str(journal_id)},
    )
    assert journal_id is not None
    return int(journal_id)


@pytest.fixture
async def checkout_journal_with_snipeit_links(
    async_connection: AsyncConnection, test_user: SessionUser
) -> int:
    # 1. Create a gear item
    gear_id = uuid.uuid4()
    await async_connection.execute(
        text(
            """
            INSERT INTO gear_items (id, user_id, name)
            VALUES (:id, :user_id, 'Test Gear')
            """
        ),
        {"id": str(gear_id), "user_id": test_user.id},
    )

    # 2. Add Snipe-IT Settings
    await _snipeit_settings(async_connection, test_user.id)

    # 3. Add Snipe-IT Asset sync metadata for the gear item
    await async_connection.execute(
        text(
            """
            INSERT INTO sync_metadata (integration_source, external_id, internal_uuid, sync_status, version_hash, last_synced_at)
            VALUES ('snipeit', '100', :gear_id, 'success', 'hash2', CURRENT_TIMESTAMP)
            """
        ),
        {"gear_id": str(gear_id)},
    )

    # 4. Create a journal
    result = await async_connection.execute(
        text(
            """
            INSERT INTO journals (user_id, title, event_date_range_start, event_date_range_end, content)
            VALUES (:user_id, 'Checkout', CURRENT_DATE, CURRENT_DATE, 'Checkout content')
            RETURNING id
            """
        ),
        {"user_id": test_user.id},
    )
    journal_id = result.scalar()

    # 5. Add Gear Usage data linking journal to gear item
    await async_connection.execute(
        text(
            """
            INSERT INTO journal_gear_usage_data (journal_id, gear_item_id)
            VALUES (:journal_id, :gear_item_id)
            """
        ),
        {"journal_id": journal_id, "gear_item_id": str(gear_id)},
    )

    # 6. Add Snipe-IT Checkout sync metadata for the journal
    await async_connection.execute(
        text(
            """
            INSERT INTO sync_metadata (integration_source, external_id, internal_uuid, sync_status, version_hash, last_synced_at)
            VALUES ('snipeit_checkout', '50', :journal_uuid, 'success', 'hash3', CURRENT_TIMESTAMP)
            """
        ),
        {"journal_uuid": str(journal_id)},
    )
    assert journal_id is not None
    return int(journal_id)


@pytest.mark.asyncio
async def test_returns_snipeit_maintenance_link(
    authenticated_client: AsyncClient,
    journal_with_snipeit_links: int,
) -> None:
    response = await authenticated_client.get(
        f"/api/journals/{journal_with_snipeit_links}/external-links"
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert len(data) == 1
    link = data[0]
    assert link["id"] == "snipeit_maintenance-maint-snipeit_maint:42"
    assert link["attributes"]["source"] == "snipeit_maintenance"
    assert (
        link["attributes"]["url"]
        == "https://snipeit.example.com/hardware/maintenances/42"
    )
    assert link["attributes"]["external_id"] == "snipeit_maint:42"


@pytest.mark.asyncio
async def test_returns_snipeit_checkout_asset_link(
    authenticated_client: AsyncClient,
    checkout_journal_with_snipeit_links: int,
) -> None:
    response = await authenticated_client.get(
        f"/api/journals/{checkout_journal_with_snipeit_links}/external-links"
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert len(data) == 1
    link = data[0]
    assert link["id"] == "snipeit-asset-100"
    assert link["attributes"]["source"] == "snipeit"
    assert link["attributes"]["url"] == "https://snipeit.example.com/hardware/100"
    assert link["attributes"]["external_id"] == "100"


@pytest.mark.asyncio
async def test_gear_item_returns_snipeit_asset_link(
    authenticated_client: AsyncClient,
    checkout_journal_with_snipeit_links: int,
    async_connection: AsyncConnection,
) -> None:
    # Retrieve the gear_item_id associated with the checkout journal
    result = await async_connection.execute(
        text(
            "SELECT gear_item_id FROM journal_gear_usage_data WHERE journal_id = :journal_id"
        ),
        {"journal_id": checkout_journal_with_snipeit_links},
    )
    gear_item_id = result.scalar()

    response = await authenticated_client.get(
        f"/api/gear-items/{gear_item_id}/external-links"
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert len(data) == 1
    link = data[0]
    assert link["id"] == "snipeit-asset-100"
    assert link["attributes"]["source"] == "snipeit"
    assert link["attributes"]["url"] == "https://snipeit.example.com/hardware/100"
    assert link["attributes"]["external_id"] == "100"


async def _maintenance_external_ids(client: AsyncClient, journal_id: int) -> list[str]:
    response = await client.get(f"/api/journals/{journal_id}/external-links")
    assert response.status_code == 200
    return [
        link["attributes"]["external_id"]
        for link in response.json()["data"]
        if link["attributes"]["source"] == _MAINTENANCE_SOURCE
    ]


@pytest.mark.asyncio
async def test_imported_journal_links_the_record_it_was_imported_from(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    test_user: SessionUser,
) -> None:
    await _snipeit_settings(async_connection, test_user.id)
    journal_id = await _journal(async_connection, test_user.id)
    await _link_import(async_connection, test_user.id, journal_id, _ORIGINAL)

    response = await authenticated_client.get(
        f"/api/journals/{journal_id}/external-links"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["attributes"]["source"] == _MAINTENANCE_SOURCE
    assert data[0]["attributes"]["external_id"] == _ORIGINAL
    assert (
        data[0]["attributes"]["url"]
        == "https://snipeit.example.com/hardware/maintenances/17"
    )


@pytest.mark.asyncio
async def test_imported_journal_hides_the_echo_its_push_created(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    test_user: SessionUser,
) -> None:
    """Journal 215032 imported #17; its pre-#1468 push echoed it as #20."""
    await _snipeit_settings(async_connection, test_user.id)
    journal_id = await _journal(async_connection, test_user.id)
    await _link_import(async_connection, test_user.id, journal_id, _ORIGINAL)
    await _record_push(async_connection, journal_id, _ECHO)

    assert await _maintenance_external_ids(authenticated_client, journal_id) == [
        _ORIGINAL
    ]


@pytest.mark.asyncio
async def test_journal_with_no_snipeit_record_has_no_maintenance_link(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    test_user: SessionUser,
) -> None:
    await _snipeit_settings(async_connection, test_user.id)
    journal_id = await _journal(async_connection, test_user.id)

    assert await _maintenance_external_ids(authenticated_client, journal_id) == []


@pytest.mark.asyncio
async def test_imported_journal_is_found_by_the_record_it_was_imported_from(
    async_connection: AsyncConnection,
    test_user: SessionUser,
) -> None:
    journal_id = await _journal(async_connection, test_user.id)
    await _link_import(async_connection, test_user.id, journal_id, _ORIGINAL)
    repo = SqlJournalRepository(async_connection)

    found = await repo.find_id_by_external_id(
        test_user.id, _MAINTENANCE_SOURCE, _ORIGINAL
    )

    assert found == journal_id
    assert await repo.find_ids_by_integration_source(
        test_user.id, _MAINTENANCE_SOURCE
    ) == {journal_id}
