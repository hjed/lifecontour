"""An applied inbound contact event records the address fallback it used (#1820).

The Google import gives an address with no country the contact's phone
country or the user's default. The push merge owns such an address only when
the last *applied* pull imported it, so the processor records the fallback on
the link's ``reference_data`` whenever it applies an event, and never when it
skips one.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]


def _event(
    sync_type: str,
    external_id: str,
    *,
    etag: str,
    fallback: str | None,
    **contact: Any,
) -> OutboxEvent:
    return OutboxEvent.create_contact_sync_event(
        contact_data={"user_id": TEST_USER_ID, "first_name": "Kiri", **contact},
        integration_source="google",
        external_id=external_id,
        sync_type=sync_type,
        etag=etag,
        user_id=TEST_USER_ID,
        address_fallback_country=fallback,
    )


async def _apply(conn: AsyncConnection, event: OutboxEvent) -> dict[str, Any]:
    return await OutboxEventProcessor(build_contact_service(conn), conn).process_event(
        event
    )


async def _reference_data(conn: AsyncConnection, external_id: str) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                """
                SELECT reference_data FROM sync_metadata
                WHERE user_id = :user_id AND integration_source = 'google'
                  AND external_id = :external_id
                """
            ),
            {"user_id": TEST_USER_ID, "external_id": external_id},
        )
    ).one()
    return dict(json.loads(row.reference_data))


@pytest.mark.asyncio
async def test_a_created_contact_records_the_fallback(
    async_connection: AsyncConnection,
) -> None:
    await _apply(
        async_connection,
        _event(
            "created", "people/c1", etag="e1", fallback="AU", tags=[{"name": "Kin"}]
        ),
    )

    recorded = await _reference_data(async_connection, "people/c1")
    assert recorded["address_fallback_country"] == "AU"
    assert recorded["synced_tags"] == ["Kin"]


@pytest.mark.asyncio
async def test_a_link_to_an_existing_contact_records_the_fallback(
    async_connection: AsyncConnection,
) -> None:
    """A person sharing a local contact's email is linked to it, not created."""
    contact_id = await seed_contact(async_connection, first_name="Kiri")
    await async_connection.execute(
        text(
            "INSERT INTO contact_methods (contact_id, method_type, value, is_primary) "
            "VALUES (:c, 'email', 'kiri@example.com', true)"
        ),
        {"c": contact_id},
    )

    result = await _apply(
        async_connection,
        _event(
            "created",
            "people/c2",
            etag="e2",
            fallback="NZ",
            methods=[{"method_type": "email", "value": "kiri@example.com"}],
        ),
    )

    assert (result["status"], result["contact_id"]) == ("success", contact_id)
    recorded = await _reference_data(async_connection, "people/c2")
    assert recorded["address_fallback_country"] == "NZ"


@pytest.mark.asyncio
async def test_an_applied_update_records_the_new_fallback_and_keeps_the_rest(
    async_connection: AsyncConnection,
) -> None:
    """Recorded even when the update carries no tags, which keep their record."""
    await _apply(
        async_connection,
        _event(
            "created", "people/c1", etag="e1", fallback="AU", tags=[{"name": "Kin"}]
        ),
    )

    await _apply(
        async_connection, _event("updated", "people/c1", etag="e2", fallback="NZ")
    )

    recorded = await _reference_data(async_connection, "people/c1")
    assert recorded["address_fallback_country"] == "NZ"
    assert recorded["synced_tags"] == ["Kin"]
    assert recorded["resource_name"] == "people/c1"


@pytest.mark.asyncio
async def test_an_applied_update_records_no_fallback(
    async_connection: AsyncConnection,
) -> None:
    """A cleared default is recorded too: the next push keeps countryless ones."""
    await _apply(
        async_connection, _event("created", "people/c1", etag="e1", fallback="AU")
    )

    await _apply(
        async_connection, _event("updated", "people/c1", etag="e2", fallback=None)
    )

    recorded = await _reference_data(async_connection, "people/c1")
    assert recorded["address_fallback_country"] is None


@pytest.mark.asyncio
async def test_a_skipped_update_leaves_the_record(
    async_connection: AsyncConnection,
) -> None:
    """An unchanged etag writes nothing, so the record still matches the contact."""
    await _apply(
        async_connection, _event("created", "people/c1", etag="e1", fallback="AU")
    )

    result = await _apply(
        async_connection, _event("updated", "people/c1", etag="e1", fallback="NZ")
    )

    assert result["status"] == "skipped"
    recorded = await _reference_data(async_connection, "people/c1")
    assert recorded["address_fallback_country"] == "AU"
