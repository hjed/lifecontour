"""Integration tests for Phase 4: writes consolidated onto ``sync_metadata``.

Every inbound contact write path persists the canonical integration link (and
its ``reference_data``) to ``sync_metadata`` only — no ``external_references``
row is written. These drive the real ``OutboxEventProcessor`` against Docker
PostgreSQL via the shared ``async_connection`` / ``clean_database`` fixtures.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)


async def _sync_metadata_row(conn: AsyncConnection, external_id: str) -> Any:
    result = await conn.execute(
        text(
            "SELECT internal_id, version_hash, reference_data FROM sync_metadata "
            "WHERE integration_source = 'google' AND external_id = :eid"
        ),
        {"eid": external_id},
    )
    return result.fetchone()


def _contact_event(
    event_type: str,
    *,
    external_id: str,
    first_name: str,
    last_name: str,
    etag: str,
    tag: str,
) -> OutboxEvent:
    """Build a Google ``contact.created`` / ``contact.updated`` event."""
    return OutboxEvent(
        event_id=f"evt-{event_type}-{external_id}",
        event_type=event_type,
        aggregate_id=0,
        event_data={
            "integration_source": "google",
            "external_id": external_id,
            "contact_data": {
                "first_name": first_name,
                "last_name": last_name,
                "tags": [{"name": tag}],
            },
            "sync_timestamp": "2026-01-01T10:00:00Z",
            "sync_type": event_type.split(".")[1],
            "etag": etag,
        },
    )


async def _seed_google_link(
    conn: AsyncConnection,
    *,
    external_id: str,
    internal_id: int,
    version_hash: str,
    reference_data: str,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO sync_metadata "
            "(internal_id, integration_source, external_id, last_synced_at, "
            "version_hash, sync_status, internal_entity_type, external_entity_type, "
            "reference_data) "
            "VALUES (:iid, 'google', :eid, now(), :vh, 'success', 'contact', "
            "'person', :rd)"
        ),
        {
            "iid": internal_id,
            "eid": external_id,
            "vh": version_hash,
            "rd": reference_data,
        },
    )


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestLinkConsolidationWrites:
    """Inbound contact writes persist the link to sync_metadata only."""

    @pytest.mark.asyncio
    async def test_contact_created_writes_sync_metadata_link_only(
        self, async_connection: AsyncConnection
    ) -> None:
        """contact.created writes one sync_metadata link (with reference_data)."""
        external_id = "people/cCreate"

        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )
        result = await processor.process_event(
            _contact_event(
                "contact.created",
                external_id=external_id,
                first_name="New",
                last_name="Contact",
                etag="etag-create",
                tag="VIP",
            )
        )

        assert result["status"] == "success"
        # One canonical sync_metadata link carrying the contact reference_data.
        row = await _sync_metadata_row(async_connection, external_id)
        assert row is not None
        assert row.internal_id == result["contact_id"]
        assert row.reference_data is not None
        ref = json.loads(row.reference_data)
        assert ref["resource_name"] == external_id
        assert ref["etag"] == "etag-create"
        assert ref["synced_tags"] == ["VIP"]

    @pytest.mark.asyncio
    async def test_contact_updated_writes_synced_tags_to_sync_metadata(
        self, async_connection: AsyncConnection
    ) -> None:
        """contact.updated writes synced_tags onto sync_metadata, never external_references."""
        external_id = "people/cUpdate"
        contact_id_result = await async_connection.execute(
            text(
                "INSERT INTO contacts (first_name, last_name) "
                "VALUES ('Old', 'Name') RETURNING id"
            )
        )
        contact_id = int(contact_id_result.scalar_one())
        await _seed_google_link(
            async_connection,
            external_id=external_id,
            internal_id=contact_id,
            version_hash="old-etag",
            reference_data=json.dumps(
                {"resource_name": external_id, "synced_tags": ["VIP"]}
            ),
        )

        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )
        result = await processor.process_event(
            _contact_event(
                "contact.updated",
                external_id=external_id,
                first_name="Old",
                last_name="Name",
                etag="new-etag",
                tag="Family",
            )
        )

        assert result["status"] == "success"
        assert result["contact_id"] == contact_id
        # synced_tags updated in the canonical link's reference_data.
        row = await _sync_metadata_row(async_connection, external_id)
        assert row is not None
        ref = json.loads(row.reference_data)
        assert ref["synced_tags"] == ["Family"]
        # The resource_name from the original link is preserved.
        assert ref["resource_name"] == external_id

    @pytest.mark.asyncio
    async def test_contact_updated_establishes_synced_tags_on_null_reference_data(
        self, async_connection: AsyncConnection
    ) -> None:
        """A link with NULL reference_data still gets synced_tags established.

        Manual Immich links (and pre-``reference_data``-column rows) carry a
        ``sync_metadata`` link with NULL ``reference_data``; a later contact
        update with tags must establish ``synced_tags`` rather than skip.
        """
        external_id = "people/cNullRef"
        contact_id_result = await async_connection.execute(
            text(
                "INSERT INTO contacts (first_name, last_name) "
                "VALUES ('Null', 'Ref') RETURNING id"
            )
        )
        contact_id = int(contact_id_result.scalar_one())
        # Link present, but no reference_data yet (NULL).
        await async_connection.execute(
            text(
                "INSERT INTO sync_metadata "
                "(internal_id, integration_source, external_id, last_synced_at, "
                "version_hash, sync_status, internal_entity_type, external_entity_type) "
                "VALUES (:iid, 'google', :eid, now(), 'old-etag', 'success', "
                "'contact', 'person')"
            ),
            {"iid": contact_id, "eid": external_id},
        )

        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )
        result = await processor.process_event(
            _contact_event(
                "contact.updated",
                external_id=external_id,
                first_name="Null",
                last_name="Ref",
                etag="new-etag",
                tag="Family",
            )
        )

        assert result["status"] == "success"
        row = await _sync_metadata_row(async_connection, external_id)
        assert row is not None
        assert row.reference_data is not None
        assert json.loads(row.reference_data)["synced_tags"] == ["Family"]
