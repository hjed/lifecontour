"""An inbound contact event at a version a push replaced is skipped (#1938).

A pull reads the person at ``e1`` and queues ``contact.updated``. Before the
backend applies it, a local edit is pushed: Google now holds ``e2``, and the push
records ``e1`` on the link as replaced. Applied, the ``e1`` event would replace
every list Google owns with its older copy, deleting what the push just added,
until the next pull re-imported ``e2``. The processor skips it instead.
"""

from __future__ import annotations

import json

import pytest
from core_shared.models.contacts.sync_scope import ContactSyncField, ContactSyncScope
from core_shared.models.outbox import OutboxEvent
from core_shared.repositories.integration_link_repository import (
    IntegrationLinkRepository,
)
from core_shared.sync_base import PENDING_IMPORT_KEY, SYNCED_ENTRIES_KEY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

_REMOTE = "people/cSuperseded"
_SCOPE = ContactSyncScope(
    fields=frozenset({ContactSyncField.FIRST_NAME, ContactSyncField.ADDRESSES})
)
_PUSHED_BASE = {"addresses": ["k-pushed"]}


def _pull(
    *, etag: str, first_name: str = "Adelaide", force_apply: bool = False
) -> OutboxEvent:
    """Google's person without the address, as a pull read it at ``etag``."""
    return OutboxEvent.create_contact_sync_event(
        contact_data={"user_id": TEST_USER_ID, "first_name": first_name},
        integration_source="google",
        external_id=_REMOTE,
        sync_type="updated",
        etag=etag,
        user_id=TEST_USER_ID,
        sync_scope=_SCOPE,
        force_apply=force_apply,
        synced_entries={"addresses": []},
        empty_at_source={ContactSyncField.ADDRESSES: "addresses"},
    )


async def _seed_pushed(conn: AsyncConnection) -> int:
    """Ada with the address a push just added, the link as that push left it."""
    contact_id = await seed_contact(conn, first_name="Ada")
    await conn.execute(
        text(
            "INSERT INTO contact_addresses (contact_id, street_line_1, country_code) "
            "VALUES (:c, '1 Pushed St', 'AU')"
        ),
        {"c": contact_id},
    )
    await conn.execute(
        text(
            "INSERT INTO sync_metadata "
            "(user_id, internal_id, integration_source, external_id, "
            "last_synced_at, version_hash, sync_status, internal_entity_type, "
            "external_entity_type, reference_data) "
            "VALUES (:u, :c, 'google', :eid, now(), 'e2', 'success', "
            "'contact', 'person', :ref)"
        ),
        {
            "u": TEST_USER_ID,
            "c": contact_id,
            "eid": _REMOTE,
            "ref": json.dumps({SYNCED_ENTRIES_KEY: _PUSHED_BASE}),
        },
    )
    await IntegrationLinkRepository(conn).record_superseded_versions(
        "google", _REMOTE, ["e0", "e1"], user_id=TEST_USER_ID
    )
    return contact_id


async def _apply(conn: AsyncConnection, event: OutboxEvent) -> dict[str, object]:
    return await OutboxEventProcessor(build_contact_service(conn), conn).process_event(
        event
    )


async def _contact(conn: AsyncConnection, contact_id: int) -> tuple[str, list[str]]:
    """The contact's first name and live addresses."""
    first_name = (
        await conn.execute(
            text("SELECT first_name FROM contacts WHERE id = :c"), {"c": contact_id}
        )
    ).scalar_one()
    streets = (
        await conn.execute(
            text(
                "SELECT street_line_1 FROM contact_addresses "
                "WHERE contact_id = :c AND NOT is_archived"
            ),
            {"c": contact_id},
        )
    ).scalars()
    return str(first_name), sorted(streets)


async def _link(conn: AsyncConnection) -> tuple[str, dict[str, object]]:
    row = (
        await conn.execute(
            text(
                "SELECT version_hash, reference_data FROM sync_metadata "
                "WHERE external_id = :eid"
            ),
            {"eid": _REMOTE},
        )
    ).one()
    return str(row.version_hash), dict(json.loads(row.reference_data))


@pytest.mark.asyncio
@pytest.mark.parametrize("etag", ["e0", "e1"])
async def test_an_event_at_a_replaced_version_is_skipped(
    async_connection: AsyncConnection, etag: str
) -> None:
    contact_id = await _seed_pushed(async_connection)
    link_before = await _link(async_connection)

    result = await _apply(async_connection, _pull(etag=etag))

    assert result["status"] == "skipped"
    assert result["reason"] == "superseded_by_push"
    assert await _contact(async_connection, contact_id) == ("Ada", ["1 Pushed St"])
    assert await _link(async_connection) == link_before


@pytest.mark.asyncio
async def test_a_full_sync_at_a_replaced_version_is_skipped(
    async_connection: AsyncConnection,
) -> None:
    """A full sync re-applies every person, but its copy is just as old."""
    contact_id = await _seed_pushed(async_connection)

    result = await _apply(async_connection, _pull(etag="e1", force_apply=True))

    assert result["reason"] == "superseded_by_push"
    assert await _contact(async_connection, contact_id) == ("Ada", ["1 Pushed St"])


@pytest.mark.asyncio
async def test_a_pending_import_does_not_apply_a_replaced_version(
    async_connection: AsyncConnection,
) -> None:
    """What the push left for the next pull is in ``e2``, not in ``e1``."""
    contact_id = await _seed_pushed(async_connection)
    await IntegrationLinkRepository(async_connection).patch_reference_data(
        "google", _REMOTE, {PENDING_IMPORT_KEY: True}, user_id=TEST_USER_ID
    )

    result = await _apply(async_connection, _pull(etag="e1"))

    assert result["reason"] == "superseded_by_push"
    assert await _contact(async_connection, contact_id) == ("Ada", ["1 Pushed St"])
    assert (await _link(async_connection))[1][PENDING_IMPORT_KEY] is True


@pytest.mark.asyncio
async def test_an_event_at_a_newer_version_is_applied(
    async_connection: AsyncConnection,
) -> None:
    """An edit made in Google after the push still reaches the contact."""
    contact_id = await _seed_pushed(async_connection)

    result = await _apply(async_connection, _pull(etag="e3"))

    assert result["status"] == "success"
    assert await _contact(async_connection, contact_id) == ("Adelaide", [])
    assert (await _link(async_connection))[0] == "e3"
