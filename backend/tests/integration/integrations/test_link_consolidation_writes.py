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

from app.core.contacts.adapters.sql import (
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactRepository,
    SqlTagRepository,
)
from app.core.contacts.services import ContactService
from app.core.integrations.outbox_event_processor import OutboxEventProcessor


def _build_contact_service(conn: AsyncConnection) -> ContactService:
    """Build a real ContactService bound to the test connection."""
    from app.core.contacts.services import (
        AddressValidationService,
        ContactHistoryService,
        ContactValidationService,
        TagHierarchyService,
        TagService,
    )

    contact_repo = SqlContactRepository(conn)
    tag_repo = SqlTagRepository(conn)
    history_repo = SqlContactFieldHistoryRepository(conn)
    event_publisher = SqlContactEventPublisher(conn)
    tag_hierarchy_service = TagHierarchyService(tag_repo)

    return ContactService(
        contact_repo=contact_repo,
        tag_repo=tag_repo,
        history_repo=history_repo,
        event_publisher=event_publisher,
        address_validation_service=AddressValidationService(),
        contact_validation_service=ContactValidationService(contact_repo),
        history_service=ContactHistoryService(history_repo),
        tag_hierarchy_service=tag_hierarchy_service,
        tag_service=TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=tag_hierarchy_service,
            event_publisher=event_publisher,
        ),
    )


async def _count_external_refs(conn: AsyncConnection) -> int:
    result = await conn.execute(text("SELECT count(*) FROM external_references"))
    return int(result.scalar_one())


async def _sync_metadata_row(conn: AsyncConnection, external_id: str) -> Any:
    result = await conn.execute(
        text(
            "SELECT internal_id, version_hash, reference_data FROM sync_metadata "
            "WHERE integration_source = 'google' AND external_id = :eid"
        ),
        {"eid": external_id},
    )
    return result.fetchone()


def _created_event(
    *, external_id: str, first_name: str, last_name: str, etag: str
) -> OutboxEvent:
    return OutboxEvent(
        event_id=f"evt-created-{external_id}",
        event_type="contact.created",
        aggregate_id=0,
        event_data={
            "integration_source": "google",
            "external_id": external_id,
            "contact_data": {
                "first_name": first_name,
                "last_name": last_name,
                "tags": [{"name": "VIP"}],
            },
            "sync_timestamp": "2026-01-01T10:00:00Z",
            "sync_type": "created",
            "etag": etag,
        },
    )


def _updated_event(
    *, external_id: str, first_name: str, last_name: str, etag: str
) -> OutboxEvent:
    return OutboxEvent(
        event_id=f"evt-updated-{external_id}",
        event_type="contact.updated",
        aggregate_id=0,
        event_data={
            "integration_source": "google",
            "external_id": external_id,
            "contact_data": {
                "first_name": first_name,
                "last_name": last_name,
                "tags": [{"name": "Family"}],
            },
            "sync_timestamp": "2026-01-02T10:00:00Z",
            "sync_type": "updated",
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
            _build_contact_service(async_connection), async_connection
        )
        result = await processor.process_event(
            _created_event(
                external_id=external_id,
                first_name="New",
                last_name="Contact",
                etag="etag-create",
            )
        )

        assert result["status"] == "success"
        # Zero external_references written.
        assert await _count_external_refs(async_connection) == 0
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
            _build_contact_service(async_connection), async_connection
        )
        result = await processor.process_event(
            _updated_event(
                external_id=external_id,
                first_name="Old",
                last_name="Name",
                etag="new-etag",
            )
        )

        assert result["status"] == "success"
        assert result["contact_id"] == contact_id
        # Zero external_references written.
        assert await _count_external_refs(async_connection) == 0
        # synced_tags updated in the canonical link's reference_data.
        row = await _sync_metadata_row(async_connection, external_id)
        assert row is not None
        ref = json.loads(row.reference_data)
        assert ref["synced_tags"] == ["Family"]
        # The resource_name from the original link is preserved.
        assert ref["resource_name"] == external_id
