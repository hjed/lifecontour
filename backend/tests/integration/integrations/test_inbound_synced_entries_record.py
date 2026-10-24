"""An applied inbound contact event records the synced base it read (#1861).

The worker's push merges against the entries both sides last agreed on, so an
entry the provider gained since is kept rather than deleted. The processor
records the event's ``synced_entries`` on the link whenever it applies one.

When a push keeps entries the contact does not hold it marks the link
``pending_import``; the next pull carries the push's own etag, and must still be
applied so the contact imports them - unless the contact has a newer local edit
still to push, which a pull must never overwrite.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from core_shared.sync_base import PENDING_IMPORT_KEY, SYNCED_ENTRIES_KEY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

_REMOTE = "people/c1"
_BASE = {"emailAddresses": ["k-email"], "addresses": []}


def _event(
    sync_type: str,
    *,
    etag: str,
    synced_entries: dict[str, list[str]] | None,
    first_name: str = "Kiri",
) -> OutboxEvent:
    return OutboxEvent.create_contact_sync_event(
        contact_data={"user_id": TEST_USER_ID, "first_name": first_name},
        integration_source="google",
        external_id=_REMOTE,
        sync_type=sync_type,
        etag=etag,
        user_id=TEST_USER_ID,
        synced_entries=synced_entries,
    )


async def _apply(conn: AsyncConnection, event: OutboxEvent) -> dict[str, Any]:
    return await OutboxEventProcessor(build_contact_service(conn), conn).process_event(
        event
    )


async def _reference_data(conn: AsyncConnection) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                """
                SELECT reference_data FROM sync_metadata
                WHERE user_id = :user_id AND integration_source = 'google'
                  AND external_id = :external_id
                """
            ),
            {"user_id": TEST_USER_ID, "external_id": _REMOTE},
        )
    ).one()
    return dict(json.loads(row.reference_data))


async def _first_name(conn: AsyncConnection) -> str:
    row = (
        await conn.execute(
            text(
                """
                SELECT c.first_name FROM contacts c
                JOIN sync_metadata sm ON sm.internal_id = c.id
                WHERE sm.external_id = :external_id
                """
            ),
            {"external_id": _REMOTE},
        )
    ).one()
    return str(row.first_name)


async def _mark_pending_import(conn: AsyncConnection) -> None:
    """What a push that kept entries the contact does not hold leaves behind."""
    await conn.execute(
        text(
            """
            UPDATE sync_metadata
            SET reference_data = (reference_data::jsonb || '{"pending_import": true}')::text
            WHERE external_id = :external_id
            """
        ),
        {"external_id": _REMOTE},
    )


@pytest.mark.asyncio
async def test_a_created_contact_records_the_base(
    async_connection: AsyncConnection,
) -> None:
    await _apply(async_connection, _event("created", etag="e1", synced_entries=_BASE))

    recorded = await _reference_data(async_connection)
    assert recorded[SYNCED_ENTRIES_KEY] == _BASE
    assert recorded[PENDING_IMPORT_KEY] is False


@pytest.mark.asyncio
async def test_an_applied_update_records_the_new_base(
    async_connection: AsyncConnection,
) -> None:
    await _apply(async_connection, _event("created", etag="e1", synced_entries=_BASE))
    newer = {"emailAddresses": ["k-email", "k-new"]}

    await _apply(async_connection, _event("updated", etag="e2", synced_entries=newer))

    recorded = await _reference_data(async_connection)
    assert recorded[SYNCED_ENTRIES_KEY] == newer
    assert recorded["resource_name"] == _REMOTE


@pytest.mark.asyncio
async def test_an_event_without_a_base_clears_the_recorded_one(
    async_connection: AsyncConnection,
) -> None:
    """A stale base could own entries this pull did not import, and delete them."""
    await _apply(async_connection, _event("created", etag="e1", synced_entries=_BASE))

    await _apply(async_connection, _event("updated", etag="e2", synced_entries=None))

    assert (await _reference_data(async_connection))[SYNCED_ENTRIES_KEY] is None


@pytest.mark.asyncio
async def test_a_skipped_update_leaves_the_base(
    async_connection: AsyncConnection,
) -> None:
    await _apply(async_connection, _event("created", etag="e1", synced_entries=_BASE))

    result = await _apply(
        async_connection,
        _event("updated", etag="e1", synced_entries={"emailAddresses": []}),
    )

    assert result["status"] == "skipped"
    assert (await _reference_data(async_connection))[SYNCED_ENTRIES_KEY] == _BASE


@pytest.mark.asyncio
async def test_a_pending_import_applies_an_unchanged_etag_and_clears(
    async_connection: AsyncConnection,
) -> None:
    await _apply(async_connection, _event("created", etag="e1", synced_entries=_BASE))
    await _mark_pending_import(async_connection)

    result = await _apply(
        async_connection,
        _event("updated", etag="e1", synced_entries=_BASE, first_name="Kirsty"),
    )

    assert result["status"] == "success"
    assert await _first_name(async_connection) == "Kirsty"
    assert (await _reference_data(async_connection))[PENDING_IMPORT_KEY] is False


@pytest.mark.asyncio
async def test_a_pending_import_never_overwrites_an_unpushed_local_edit(
    async_connection: AsyncConnection,
) -> None:
    """The edit's push failed or is queued; the pull waits for it."""
    await _apply(async_connection, _event("created", etag="e1", synced_entries=_BASE))
    await _mark_pending_import(async_connection)
    await async_connection.execute(
        text(
            "UPDATE sync_metadata SET last_synced_at = now() - interval '1 hour' "
            "WHERE external_id = :external_id"
        ),
        {"external_id": _REMOTE},
    )

    result = await _apply(
        async_connection,
        _event("updated", etag="e1", synced_entries=_BASE, first_name="Kirsty"),
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "unpushed_local_changes"
    assert await _first_name(async_connection) == "Kiri"
    assert (await _reference_data(async_connection))[PENDING_IMPORT_KEY] is True
