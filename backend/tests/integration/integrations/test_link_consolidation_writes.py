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

from app.core.integrations.outbox_event_processor import (
    OutboxEventProcessingError,
    OutboxEventProcessor,
    PermanentOutboxEventProcessingError,
)
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)


async def _sync_metadata_row(conn: AsyncConnection, external_id: str) -> Any:
    result = await conn.execute(
        text(
            "SELECT user_id, internal_id, version_hash, reference_data "
            "FROM sync_metadata "
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
            "user_id": TEST_USER_ID,
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
    user_id: str | None = TEST_USER_ID,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO sync_metadata "
            "(user_id, internal_id, integration_source, external_id, last_synced_at, "
            "version_hash, sync_status, internal_entity_type, external_entity_type, "
            "reference_data) "
            "VALUES (:uid, :iid, 'google', :eid, now(), :vh, 'success', 'contact', "
            "'person', :rd)"
        ),
        {
            "uid": user_id,
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
        assert row.user_id == TEST_USER_ID
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
        contact_id = await seed_contact(
            async_connection, first_name="Old", last_name="Name"
        )
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
        contact_id = await seed_contact(
            async_connection, first_name="Null", last_name="Ref"
        )
        # Link present, but no reference_data yet (NULL).
        await async_connection.execute(
            text(
                "INSERT INTO sync_metadata "
                "(user_id, internal_id, integration_source, external_id, "
                "last_synced_at, version_hash, sync_status, internal_entity_type, "
                "external_entity_type) "
                "VALUES (:uid, :iid, 'google', :eid, now(), 'old-etag', 'success', "
                "'contact', 'person')"
            ),
            {"uid": TEST_USER_ID, "iid": contact_id, "eid": external_id},
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


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestInboundLinkOwner:
    """An inbound contact never takes over an external id another user links."""

    @pytest.mark.asyncio
    async def test_another_users_link_fails_the_event_permanently(
        self, async_connection: AsyncConnection
    ) -> None:
        external_id = "people/cTaken"
        # Another user's link that names no contact yet, so the idempotency
        # check does not short-circuit and the creation reaches the link write.
        await async_connection.execute(
            text(
                "INSERT INTO sync_metadata "
                "(user_id, integration_source, external_id, last_synced_at, "
                "version_hash, sync_status) "
                "VALUES ('other-user-456', 'google', :eid, now(), 'theirs', 'pending')"
            ),
            {"eid": external_id},
        )
        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )

        with pytest.raises(PermanentOutboxEventProcessingError):
            await processor.process_event(
                _contact_event(
                    "contact.created",
                    external_id=external_id,
                    first_name="Mine",
                    last_name="Too",
                    etag="etag-mine",
                    tag="VIP",
                )
            )

        row = await _sync_metadata_row(async_connection, external_id)
        assert row is not None
        assert (row.user_id, row.internal_id, row.version_hash) == (
            "other-user-456",
            None,
            "theirs",
        )

    @pytest.mark.asyncio
    async def test_another_users_link_is_not_this_users_processed_event(
        self, async_connection: AsyncConnection
    ) -> None:
        """The idempotency check reads the event owner's links only: another
        user's contact for the same external id never answers this user's
        ``contact.created`` as already processed."""
        external_id = "people/cTheirs"
        their_contact = await seed_contact(
            async_connection, user_id="other-user-456", first_name="Theirs"
        )
        await _seed_google_link(
            async_connection,
            external_id=external_id,
            internal_id=their_contact,
            version_hash="theirs",
            reference_data=json.dumps({"resource_name": external_id}),
            user_id="other-user-456",
        )
        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )

        # Until the global key goes the link write is refused; what matters is
        # that the event was not resolved to the other user's contact.
        with pytest.raises(PermanentOutboxEventProcessingError):
            await processor.process_event(
                _contact_event(
                    "contact.created",
                    external_id=external_id,
                    first_name="Mine",
                    last_name="Too",
                    etag="etag-mine",
                    tag="VIP",
                )
            )

    @pytest.mark.asyncio
    async def test_an_update_whose_link_has_no_owner_yet_is_retried(
        self, async_connection: AsyncConnection
    ) -> None:
        """A link written owner-less (a pre-release writer, mid rolling deploy)
        does not match the owner-keyed upsert. The update fails retryably
        rather than being acknowledged with the link's version hash stale."""
        external_id = "people/cUnowned"
        contact_id = await seed_contact(
            async_connection, first_name="Old", last_name="Name"
        )
        await _seed_google_link(
            async_connection,
            external_id=external_id,
            internal_id=contact_id,
            version_hash="old-etag",
            reference_data=json.dumps({"resource_name": external_id}),
            user_id=None,
        )
        processor = OutboxEventProcessor(
            build_contact_service(async_connection), async_connection
        )

        with pytest.raises(OutboxEventProcessingError) as failed:
            await processor.process_event(
                _contact_event(
                    "contact.updated",
                    external_id=external_id,
                    first_name="New",
                    last_name="Name",
                    etag="new-etag",
                    tag="VIP",
                )
            )

        assert not isinstance(failed.value, PermanentOutboxEventProcessingError)
