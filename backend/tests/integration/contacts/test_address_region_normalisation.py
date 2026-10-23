"""Every address write stores a known region as its code (#1820).

A region typed as a name ("New South Wales"), in lower case, or left blank is
accepted, and a recognised one is stored as its ISO 3166-2 code. No postcode
fails. An AU/US/CA region no subdivision matches is rejected on a write; the
Google import skips such an address rather than send it.
"""

from __future__ import annotations

import pytest
from core_shared.models.contacts.entities import Contact, ContactAddress
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]


def _address(region: str | None, *, postal_code: str | None = None) -> ContactAddress:
    return ContactAddress(
        street_line_1="1 George St",
        country_code="AU",
        region=region,
        postal_code=postal_code,
        contact_id=0,
    )


async def _stored(
    conn: AsyncConnection, contact_id: int
) -> list[tuple[str | None, str | None]]:
    rows = await conn.execute(
        text(
            "SELECT region, postal_code FROM contact_addresses "
            "WHERE contact_id = :c ORDER BY id"
        ),
        {"c": contact_id},
    )
    return [(row.region, row.postal_code) for row in rows]


async def _create(
    service: ContactService, conn: AsyncConnection, *addresses: ContactAddress
) -> int:
    contact = await service.create_contact(
        Contact(first_name="Kiri", user_id=TEST_USER_ID, addresses=list(addresses)),
        conn,
    )
    assert contact.id is not None
    return contact.id


@pytest.mark.asyncio
async def test_create_stores_codes_and_any_postcode(
    async_connection: AsyncConnection,
) -> None:
    service = build_contact_service(async_connection)

    contact_id = await _create(
        service,
        async_connection,
        _address("new south wales", postal_code="#2000."),
    )

    assert await _stored(async_connection, contact_id) == [("NSW", "#2000.")]


@pytest.mark.asyncio
async def test_update_stores_codes(async_connection: AsyncConnection) -> None:
    service = build_contact_service(async_connection)
    contact_id = await _create(service, async_connection)
    contact = await service.get_contact_by_id(contact_id, user_id=TEST_USER_ID)
    assert contact is not None
    contact.addresses = [_address("Victoria"), _address("  ")]

    await service.update_contact(contact, async_connection, user_id=TEST_USER_ID)

    assert await _stored(async_connection, contact_id) == [("VIC", None), (None, None)]


@pytest.mark.asyncio
async def test_add_address_stores_the_code(async_connection: AsyncConnection) -> None:
    service = build_contact_service(async_connection)
    contact_id = await _create(service, async_connection)

    await service.add_contact_address(
        contact_id, _address("queensland"), async_connection, user_id=TEST_USER_ID
    )

    assert await _stored(async_connection, contact_id) == [("QLD", None)]


@pytest.mark.asyncio
async def test_a_region_field_edit_stores_the_code(
    async_connection: AsyncConnection,
) -> None:
    service = build_contact_service(async_connection)
    contact_id = await _create(service, async_connection, _address("NSW"))
    contact = await service.get_contact_by_id(contact_id, user_id=TEST_USER_ID)
    assert contact is not None and contact.addresses
    address_id = contact.addresses[0].id
    assert address_id is not None

    await service.update_contact_address_field(
        contact_id,
        address_id,
        "region",
        "western australia",
        async_connection,
        user_id=TEST_USER_ID,
    )

    assert await _stored(async_connection, contact_id) == [("WA", None)]


@pytest.mark.asyncio
async def test_an_import_with_a_typed_region_is_applied(
    async_connection: AsyncConnection,
) -> None:
    """Before #1820 a typed state name failed the whole contact event."""
    event = OutboxEvent.create_contact_sync_event(
        contact_data={
            "user_id": TEST_USER_ID,
            "first_name": "Kiri",
            "addresses": [
                {
                    "street_line_1": "1 George St",
                    "country_code": "AU",
                    "region": "New South Wales",
                    "postal_code": "2000",
                }
            ],
        },
        integration_source="google",
        external_id="people/cRegion",
        sync_type="created",
        etag="e1",
        user_id=TEST_USER_ID,
    )

    result = await OutboxEventProcessor(
        build_contact_service(async_connection), async_connection
    ).process_event(event)

    assert result["status"] == "success"
    assert await _stored(async_connection, result["contact_id"]) == [("NSW", "2000")]


@pytest.mark.asyncio
async def test_an_unrecognised_region_is_rejected(
    async_connection: AsyncConnection,
) -> None:
    service = build_contact_service(async_connection)
    contact_id = await _create(service, async_connection)

    with pytest.raises(ContactValidationError) as exc_info:
        await service.add_contact_address(
            contact_id, _address("London"), async_connection, user_id=TEST_USER_ID
        )

    assert exc_info.value.field == "region"
