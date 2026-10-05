"""Inbound contact syncs keep a contact's archived values.

Archived values are never pushed to a provider, so the provider's whole-list
payload never holds them. The sync must not read that absence as a deletion;
and a value the provider holds again is restored rather than duplicated.
"""

from __future__ import annotations

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

EXTERNAL_ID = "people/cArchived"


def _event(event_type: str, emails: list[str]) -> OutboxEvent:
    return OutboxEvent(
        event_id=f"evt-{event_type}-{'-'.join(emails)}",
        event_type=event_type,
        aggregate_id=0,
        event_data={
            "integration_source": "google",
            "external_id": EXTERNAL_ID,
            "contact_data": {
                "first_name": "Ada",
                "methods": [
                    {"method_type": "email", "value": email, "is_primary": i == 0}
                    for i, email in enumerate(emails)
                ],
                "addresses": [],
            },
            "sync_timestamp": "2026-01-01T10:00:00Z",
            "sync_type": event_type.split(".")[1],
            "user_id": TEST_USER_ID,
            "etag": f"etag-{'-'.join(emails)}",
        },
    )


async def _seed_contact(conn: AsyncConnection, *, linked: bool) -> dict[str, int]:
    """Ada: an active primary email, an archived email and an archived address."""
    contact_id = await seed_contact(conn, first_name="Ada")
    archived_email_id = (
        await conn.execute(
            text(
                "INSERT INTO contact_methods "
                "(contact_id, method_type, value, is_primary, is_archived) "
                "VALUES (:c, 'email', 'now@example.com', true, false), "
                "(:c, 'email', 'then@example.com', false, true) "
                "RETURNING id"
            ),
            {"c": contact_id},
        )
    ).fetchall()[1][0]
    archived_address_id = (
        await conn.execute(
            text(
                "INSERT INTO contact_addresses "
                "(contact_id, street_line_1, country_code, is_archived) "
                "VALUES (:c, '1 Childhood Rd', 'AU', true) RETURNING id"
            ),
            {"c": contact_id},
        )
    ).scalar_one()
    if linked:
        await conn.execute(
            text(
                "INSERT INTO sync_metadata "
                "(internal_id, integration_source, external_id, last_synced_at, "
                "version_hash, sync_status, internal_entity_type, "
                "external_entity_type) "
                "VALUES (:c, 'google', :eid, now(), 'old', 'success', 'contact', "
                "'person')"
            ),
            {"c": contact_id, "eid": EXTERNAL_ID},
        )
    return {
        "contact": contact_id,
        "archived_email": archived_email_id,
        "archived_address": archived_address_id,
    }


async def _methods(conn: AsyncConnection, contact_id: int) -> dict[str, Any]:
    rows = await conn.execute(
        text(
            "SELECT id, value, is_archived FROM contact_methods WHERE contact_id = :c"
        ),
        {"c": contact_id},
    )
    return {row.value: (row.id, row.is_archived) for row in rows}


async def _address_archived(conn: AsyncConnection, address_id: int) -> Any:
    return (
        await conn.execute(
            text("SELECT is_archived FROM contact_addresses WHERE id = :id"),
            {"id": address_id},
        )
    ).scalar_one_or_none()


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestInboundSyncKeepsArchivedValues:
    @pytest.mark.asyncio
    async def test_update_without_the_archived_values_keeps_them(
        self, async_connection: AsyncConnection
    ) -> None:
        ids = await _seed_contact(async_connection, linked=True)
        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )

        result = await processor.process_event(
            _event("contact.updated", ["now@example.com"])
        )

        assert result["status"] == "success"
        methods = await _methods(async_connection, ids["contact"])
        assert methods["then@example.com"] == (ids["archived_email"], True)
        assert methods["now@example.com"][1] is False
        assert await _address_archived(async_connection, ids["archived_address"])

    @pytest.mark.asyncio
    async def test_update_holding_an_archived_value_restores_it(
        self, async_connection: AsyncConnection
    ) -> None:
        ids = await _seed_contact(async_connection, linked=True)
        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )

        result = await processor.process_event(
            _event("contact.updated", ["now@example.com", "THEN@example.com"])
        )

        assert result["status"] == "success"
        methods = await _methods(async_connection, ids["contact"])
        assert len(methods) == 2
        # The archived row itself is restored, not a second copy inserted.
        assert methods["THEN@example.com"] == (ids["archived_email"], False)

    @pytest.mark.asyncio
    async def test_create_reconciled_by_email_keeps_archived_values(
        self, async_connection: AsyncConnection
    ) -> None:
        ids = await _seed_contact(async_connection, linked=False)
        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )

        result = await processor.process_event(
            _event("contact.created", ["now@example.com"])
        )

        assert result["status"] == "success"
        assert result["contact_id"] == ids["contact"]
        methods = await _methods(async_connection, ids["contact"])
        assert methods["then@example.com"] == (ids["archived_email"], True)
        assert await _address_archived(async_connection, ids["archived_address"])
