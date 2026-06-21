"""Integration tests for Phase 3: reads keyed on ``sync_metadata``.

These reproduce the contact-duplication loop the consolidation fixes and assert
the reader now resolves links from the canonical ``sync_metadata`` store rather
than ``external_references``. Each test seeds links **only** in ``sync_metadata``
(mirroring the bug shape: a Google outbound push writes ``sync_metadata`` but no
``external_references`` row) and asserts no duplicate contact is created.
"""

from __future__ import annotations

from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactRepository
from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)


async def _insert_email_less_contact(
    conn: AsyncConnection, first_name: str, last_name: str
) -> int:
    """Insert a contact with no email method and return its id."""
    result = await conn.execute(
        text(
            "INSERT INTO contacts (first_name, last_name) "
            "VALUES (:first_name, :last_name) RETURNING id"
        ),
        {"first_name": first_name, "last_name": last_name},
    )
    return int(result.scalar_one())


async def _seed_sync_metadata(
    conn: AsyncConnection,
    *,
    integration_source: str,
    external_id: str,
    internal_id: int,
    version_hash: str,
    internal_entity_type: str = "contact",
    external_entity_type: str = "person",
) -> None:
    """Seed a canonical link row in sync_metadata only (no external_references)."""
    await conn.execute(
        text(
            "INSERT INTO sync_metadata "
            "(internal_id, integration_source, external_id, last_synced_at, "
            "version_hash, sync_status, internal_entity_type, external_entity_type) "
            "VALUES (:internal_id, :integration_source, :external_id, now(), "
            ":version_hash, 'success', :internal_entity_type, :external_entity_type)"
        ),
        {
            "internal_id": internal_id,
            "integration_source": integration_source,
            "external_id": external_id,
            "version_hash": version_hash,
            "internal_entity_type": internal_entity_type,
            "external_entity_type": external_entity_type,
        },
    )


async def _count_contacts(conn: AsyncConnection) -> int:
    result = await conn.execute(text("SELECT count(*) FROM contacts"))
    return int(result.scalar_one())


def _contact_event(
    event_type: str,
    *,
    external_id: str,
    first_name: str,
    last_name: str,
    etag: str,
) -> OutboxEvent:
    """Build a Google contact sync OutboxEvent payload."""
    return OutboxEvent(
        event_id=f"evt-{event_type}-{external_id}",
        event_type=event_type,
        aggregate_id=0,
        event_data={
            "integration_source": "google",
            "external_id": external_id,
            "contact_data": {"first_name": first_name, "last_name": last_name},
            "sync_timestamp": "2026-01-01T10:00:00Z",
            "sync_type": event_type.split(".")[1],
            "etag": etag,
        },
    )


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestLinkConsolidationReads:
    """The duplication loop is closed by reading links from sync_metadata."""

    @pytest.mark.asyncio
    async def test_contact_updated_for_synced_metadata_link_updates_not_duplicates(
        self, async_connection: AsyncConnection
    ) -> None:
        """The bug shape: google link only in sync_metadata → update, no duplicate.

        Reproduces an email-less Immich contact pushed to Google (which writes
        ``sync_metadata(google, …)`` but no ``external_references(google, …)``).
        A subsequent Google ``contact.updated`` must resolve the existing contact
        and update it, never create a second one.
        """
        contact_id = await _insert_email_less_contact(
            async_connection, "Ada", "Lovelace"
        )
        google_external_id = "people/cAda"
        await _seed_sync_metadata(
            async_connection,
            integration_source="immich",
            external_id="immich-person-ada",
            internal_id=contact_id,
            version_hash="immich-vh",
        )
        await _seed_sync_metadata(
            async_connection,
            integration_source="google",
            external_id=google_external_id,
            internal_id=contact_id,
            version_hash="old-etag",
        )

        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )
        result = await processor.process_event(
            _contact_event(
                "contact.updated",
                external_id=google_external_id,
                first_name="Ada",
                last_name="Lovelace-Byron",
                etag="new-etag",
            )
        )

        assert result["status"] == "success"
        assert result["contact_id"] == contact_id
        assert await _count_contacts(async_connection) == 1

    @pytest.mark.asyncio
    async def test_contact_created_for_existing_link_is_skipped(
        self, async_connection: AsyncConnection
    ) -> None:
        """Re-delivering contact.created for an already-linked id is idempotent."""
        contact_id = await _insert_email_less_contact(
            async_connection, "Grace", "Hopper"
        )
        google_external_id = "people/cGrace"
        await _seed_sync_metadata(
            async_connection,
            integration_source="google",
            external_id=google_external_id,
            internal_id=contact_id,
            version_hash="etag-1",
        )

        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )
        result = await processor.process_event(
            _contact_event(
                "contact.created",
                external_id=google_external_id,
                first_name="Grace",
                last_name="Hopper",
                etag="etag-1",
            )
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "already_processed"
        assert result["contact_id"] == contact_id
        assert await _count_contacts(async_connection) == 1

    @pytest.mark.asyncio
    async def test_get_external_references_reads_from_sync_metadata(
        self, async_connection: AsyncConnection
    ) -> None:
        """Contact external references are resolved from sync_metadata."""
        contact_id = await _insert_email_less_contact(
            async_connection, "Alan", "Turing"
        )
        await _seed_sync_metadata(
            async_connection,
            integration_source="google",
            external_id="people/cAlan",
            internal_id=contact_id,
            version_hash="g",
        )
        await _seed_sync_metadata(
            async_connection,
            integration_source="immich",
            external_id="immich-person-alan",
            internal_id=contact_id,
            version_hash="i",
        )

        repo = SqlContactRepository(async_connection)
        refs = await repo.get_external_references(contact_id)

        by_system: dict[str, dict[str, Any]] = {
            ref["external_system"]: ref for ref in refs
        }
        assert set(by_system) == {"google", "immich"}
        assert by_system["google"]["external_entity_id"] == "people/cAlan"
        assert by_system["google"]["external_entity_type"] == "person"
        assert by_system["immich"]["external_entity_id"] == "immich-person-alan"
