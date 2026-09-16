import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.auth.models import SessionUser


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
    await async_connection.execute(
        text(
            """
            INSERT INTO snipeit_settings (user_id, base_url, snipeit_user_id, webhook_token)
            VALUES (:user_id, 'https://snipeit.example.com', '123', :webhook_token)
            """
        ),
        {"user_id": test_user.id, "webhook_token": f"webhook-token-{test_user.id}"},
    )

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
    await async_connection.execute(
        text(
            """
            INSERT INTO snipeit_settings (user_id, base_url, snipeit_user_id, webhook_token)
            VALUES (:user_id, 'https://snipeit.example.com', '123', :webhook_token)
            """
        ),
        {"user_id": test_user.id, "webhook_token": f"webhook-token-{test_user.id}"},
    )

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
    authenticated_client,
    journal_with_snipeit_links: int,
):
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
    authenticated_client,
    checkout_journal_with_snipeit_links: int,
):
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
    authenticated_client,
    checkout_journal_with_snipeit_links: int,
    async_connection: AsyncConnection,
):
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
