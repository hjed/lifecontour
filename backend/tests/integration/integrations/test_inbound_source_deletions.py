"""An inbound contact event applies a list the source emptied since the last sync (#1909).

A source sends None for a list it holds no entries in, so a contact it never
held entries for keeps its local ones. When the link's synced base recorded
entries for that list, the source deleted them all since the last sync: the
processor clears the list (archived values kept), or the next push would
recreate them at the source.
"""

from __future__ import annotations

import json

import pytest
from core_shared.models.contacts.sync_scope import ContactSyncField, ContactSyncScope
from core_shared.models.outbox import OutboxEvent
from core_shared.sync_base import PENDING_IMPORT_KEY, SYNCED_ENTRIES_KEY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

_REMOTE = "people/cEmptied"
_SCOPE = ContactSyncScope(
    fields=frozenset({ContactSyncField.FIRST_NAME, ContactSyncField.ADDRESSES})
)
_EMPTY_ADDRESSES = {ContactSyncField.ADDRESSES: "addresses"}
_EMPTIED_BASE: dict[str, list[str]] = {"addresses": []}


def _update(
    *,
    etag: str = "e2",
    empty_at_source: dict[ContactSyncField, str] | None = _EMPTY_ADDRESSES,
) -> OutboxEvent:
    """Google's person with no addresses left, as the worker emits it."""
    return OutboxEvent.create_contact_sync_event(
        contact_data={"user_id": TEST_USER_ID, "first_name": "Ada"},
        integration_source="google",
        external_id=_REMOTE,
        sync_type="updated",
        etag=etag,
        user_id=TEST_USER_ID,
        sync_scope=_SCOPE,
        synced_entries=_EMPTIED_BASE,
        empty_at_source=empty_at_source,
    )


async def _seed(conn: AsyncConnection, *, base: dict[str, list[str]]) -> int:
    """Ada, linked with ``base``: an address and an archived address."""
    contact_id = await seed_contact(conn, first_name="Ada")
    await conn.execute(
        text(
            "INSERT INTO contact_addresses "
            "(contact_id, street_line_1, country_code, is_archived) "
            "VALUES (:c, '1 Synced St', 'AU', false), "
            "(:c, '1 Childhood Rd', 'AU', true)"
        ),
        {"c": contact_id},
    )
    await conn.execute(
        text(
            "INSERT INTO sync_metadata "
            "(user_id, internal_id, integration_source, external_id, "
            "last_synced_at, version_hash, sync_status, internal_entity_type, "
            "external_entity_type, reference_data) "
            "VALUES (:u, :c, 'google', :eid, now(), 'e1', 'success', "
            "'contact', 'person', :ref)"
        ),
        {
            "u": TEST_USER_ID,
            "c": contact_id,
            "eid": _REMOTE,
            "ref": json.dumps({SYNCED_ENTRIES_KEY: base}),
        },
    )
    return contact_id


async def _apply(conn: AsyncConnection, event: OutboxEvent) -> str:
    result = await OutboxEventProcessor(
        build_contact_service(conn), conn
    ).process_event(event)
    return str(result["status"])


async def _addresses(conn: AsyncConnection, contact_id: int) -> dict[str, bool]:
    rows = await conn.execute(
        text(
            "SELECT street_line_1, is_archived FROM contact_addresses "
            "WHERE contact_id = :c"
        ),
        {"c": contact_id},
    )
    return {row.street_line_1: row.is_archived for row in rows}


async def _reference_data(conn: AsyncConnection) -> dict[str, object]:
    raw = (
        await conn.execute(
            text("SELECT reference_data FROM sync_metadata WHERE external_id = :eid"),
            {"eid": _REMOTE},
        )
    ).scalar_one()
    return dict(json.loads(raw))


@pytest.mark.asyncio
async def test_the_last_address_deleted_at_the_source_is_deleted(
    async_connection: AsyncConnection,
) -> None:
    contact_id = await _seed(async_connection, base={"addresses": ["k-addr"]})

    assert await _apply(async_connection, _update()) == "success"

    assert await _addresses(async_connection, contact_id) == {"1 Childhood Rd": True}
    recorded = await _reference_data(async_connection)
    assert recorded[SYNCED_ENTRIES_KEY] == _EMPTIED_BASE
    assert recorded[PENDING_IMPORT_KEY] is False


@pytest.mark.asyncio
async def test_addresses_the_source_never_held_are_kept(
    async_connection: AsyncConnection,
) -> None:
    contact_id = await _seed(async_connection, base={"addresses": []})

    assert await _apply(async_connection, _update()) == "success"

    assert await _addresses(async_connection, contact_id) == {
        "1 Synced St": False,
        "1 Childhood Rd": True,
    }


@pytest.mark.asyncio
async def test_addresses_are_kept_while_the_source_still_holds_some(
    async_connection: AsyncConnection,
) -> None:
    """The source holds only addresses inbound cannot import, so none are keyed."""
    contact_id = await _seed(async_connection, base={"addresses": ["k-addr"]})

    assert await _apply(async_connection, _update(empty_at_source=None)) == "success"

    assert await _addresses(async_connection, contact_id) == {
        "1 Synced St": False,
        "1 Childhood Rd": True,
    }


@pytest.mark.asyncio
async def test_a_pending_import_applies_the_deletion(
    async_connection: AsyncConnection,
) -> None:
    """A push held the address back because Google had deleted it (#1861)."""
    contact_id = await _seed(async_connection, base={"addresses": ["k-addr"]})
    await async_connection.execute(
        text(
            "UPDATE sync_metadata SET reference_data = "
            "(reference_data::jsonb || '{\"pending_import\": true}')::text "
            "WHERE external_id = :eid"
        ),
        {"eid": _REMOTE},
    )

    assert await _apply(async_connection, _update(etag="e1")) == "success"

    assert await _addresses(async_connection, contact_id) == {"1 Childhood Rd": True}
    assert (await _reference_data(async_connection))[PENDING_IMPORT_KEY] is False
