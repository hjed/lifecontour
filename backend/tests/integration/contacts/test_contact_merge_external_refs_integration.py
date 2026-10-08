"""Integration tests for integration-link reconciliation during contact merge.

A contact merge must not leave the source's canonical ``sync_metadata`` link
pointing at the deleted source (the table has no ``ON DELETE CASCADE``). The
merge re-points links for services the survivor lacks, and for a same-service
collision keeps the survivor's link, removes the source's row, and flags the
collision once on the ``ContactMerged`` event for the worker phases to reconcile
remotely. Since ITER15-001 the re-point operates on the canonical
``sync_metadata`` link store via ``SyncMetadataRepository.repoint_contact_links``
(``external_references`` has been retired).

Drives the real ``ContactMergeService`` and ``SyncMetadataRepository`` against a
Docker PostgreSQL database via the ``async_connection`` / ``clean_database``
fixtures from ``tests/integration/conftest.py`` (never a custom DB provider).
"""

from collections.abc import Sequence
from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.contacts.entities import Contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRelationshipRepository,
    SqlContactRepository,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    DomainEventProtocol,
)
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.tasks.adapters.sql.task_contact_repository import (
    SqlTaskContactRepository,
)
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.contact_seeding import TEST_USER_ID


class RecordingEventPublisher(ContactEventPublisher):
    """A ``ContactEventPublisher`` that records published events for assertions."""

    def __init__(self) -> None:
        self.events: list[DomainEventProtocol] = []

    async def publish(self, event: DomainEventProtocol) -> None:
        self.events.append(event)

    async def publish_batch(self, events: Sequence[DomainEventProtocol]) -> None:
        self.events.extend(events)


@pytest_asyncio.fixture
async def contact_repo(async_connection: AsyncConnection) -> SqlContactRepository:
    return SqlContactRepository(async_connection)


@pytest_asyncio.fixture
async def event_publisher() -> RecordingEventPublisher:
    return RecordingEventPublisher()


@pytest_asyncio.fixture
async def merge_service(
    async_connection: AsyncConnection,
    contact_repo: SqlContactRepository,
    event_publisher: RecordingEventPublisher,
) -> ContactMergeService:
    return ContactMergeService(
        contact_repo=contact_repo,
        relationship_repo=SqlContactRelationshipRepository(async_connection),
        journal_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        event_publisher=event_publisher,
        history_repo=SqlFieldHistoryRepository(async_connection),
        sync_metadata_repo=SyncMetadataRepository(async_connection),
        task_merge_service=TaskContactMergeService(
            task_contact_repo=SqlTaskContactRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
        ),
    )


async def _make_contact(repo: SqlContactRepository, first_name: str) -> int:
    saved = await repo.save(Contact(user_id=TEST_USER_ID, first_name=first_name))
    assert saved.id is not None
    return saved.id


async def _add_sync_metadata(
    connection: AsyncConnection,
    internal_id: int,
    integration_source: str,
    external_id: str,
    *,
    internal_entity_type: str = "contact",
    external_entity_type: str = "person",
) -> None:
    # Dual-write/backfill always populate the entity-type columns; the collision
    # reads filter on internal_entity_type='contact', so seed them like production.
    await connection.execute(
        text(
            """
            INSERT INTO sync_metadata (
                internal_id, integration_source, external_id, last_synced_at,
                version_hash, sync_status, retry_count,
                internal_entity_type, external_entity_type, created_at, updated_at
            ) VALUES (
                :iid, :source, :eid, now(), 'h', 'success', 0,
                :internal_entity_type, :external_entity_type, now(), now()
            )
            """
        ),
        {
            "iid": internal_id,
            "source": integration_source,
            "eid": external_id,
            "internal_entity_type": internal_entity_type,
            "external_entity_type": external_entity_type,
        },
    )


async def _linked_systems(connection: AsyncConnection, contact_id: int) -> set[str]:
    """The integration sources linked to a contact in the canonical store."""
    result = await connection.execute(
        text(
            "SELECT integration_source FROM sync_metadata "
            "WHERE internal_entity_type = 'contact' AND internal_id = :cid"
        ),
        {"cid": contact_id},
    )
    return {row.integration_source for row in result.fetchall()}


async def _count_sync_metadata(connection: AsyncConnection, internal_id: int) -> int:
    result = await connection.execute(
        text("SELECT count(*) FROM sync_metadata WHERE internal_id = :iid"),
        {"iid": internal_id},
    )
    return int(result.scalar_one())


def _contact_merged_collisions(
    event_publisher: RecordingEventPublisher,
) -> list[dict[str, Any]]:
    merged = [e for e in event_publisher.events if e.event_type == "ContactMerged"]
    assert len(merged) == 1, "exactly one ContactMerged event expected"
    collisions: list[dict[str, Any]] = merged[0].event_data["external_collisions"]
    return collisions


class TestDifferentServiceCarryOver:
    """Links to services the survivor lacks carry over onto the survivor."""

    @pytest.mark.asyncio
    async def test_different_service_links_land_on_survivor(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
        event_publisher: RecordingEventPublisher,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_sync_metadata(async_connection, survivor_id, "google", "people/surv")
        await _add_sync_metadata(async_connection, source_id, "immich", "person-uuid")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        assert await _linked_systems(async_connection, survivor_id) == {
            "google",
            "immich",
        }
        assert await _count_sync_metadata(async_connection, source_id) == 0
        assert await _count_sync_metadata(async_connection, survivor_id) == 2
        # Carrying over is not a collision.
        assert _contact_merged_collisions(event_publisher) == []


class TestSameServiceCollision:
    """A service present on both contacts is flagged once; survivor's link kept."""

    @pytest.mark.asyncio
    async def test_same_service_collision_flagged_once(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
        event_publisher: RecordingEventPublisher,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_sync_metadata(async_connection, survivor_id, "google", "people/surv")
        await _add_sync_metadata(async_connection, source_id, "google", "people/src")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        # Survivor keeps exactly its own google link; the source's is removed.
        survivor_refs = await async_connection.execute(
            text(
                "SELECT integration_source, external_id FROM sync_metadata "
                "WHERE internal_entity_type = 'contact' AND internal_id = :cid"
            ),
            {"cid": survivor_id},
        )
        rows = survivor_refs.fetchall()
        assert [(r.integration_source, r.external_id) for r in rows] == [
            ("google", "people/surv")
        ]

        collisions = _contact_merged_collisions(event_publisher)
        assert collisions == [
            {
                "external_system": "google",
                "external_entity_type": "person",
                "source_external_id": "people/src",
                "survivor_external_id": "people/surv",
            }
        ]

    @pytest.mark.asyncio
    async def test_unrelated_sync_row_sharing_source_id_is_untouched(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        """``sync_metadata.internal_id`` is not entity-typed: a journal's sync row
        may share the source contact's integer id. Scoping by ``(integration_source,
        external_id)`` (tied to the contact's external reference) must leave that
        unrelated row untouched."""
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_sync_metadata(async_connection, source_id, "google", "people/src")
        # An unrelated journal album sync row that merely shares the integer id.
        await _add_sync_metadata(
            async_connection,
            source_id,
            "immich_album",
            "album-uuid",
            internal_entity_type="journal",
            external_entity_type="album",
        )

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        # The contact's google sync row carried over; the unrelated album row stays
        # exactly as it was (still pointing at the original integer id).
        unrelated = await async_connection.execute(
            text(
                "SELECT count(*) FROM sync_metadata "
                "WHERE internal_id = :iid AND integration_source = 'immich_album'"
            ),
            {"iid": source_id},
        )
        assert int(unrelated.scalar_one()) == 1

    @pytest.mark.asyncio
    async def test_no_rows_remain_pointing_at_deleted_source(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        merge_service: ContactMergeService,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_sync_metadata(async_connection, survivor_id, "google", "people/surv")
        await _add_sync_metadata(async_connection, source_id, "google", "people/src")
        await _add_sync_metadata(async_connection, source_id, "immich", "person-uuid")

        await merge_service.merge_contacts(
            survivor_id, source_id, transaction=async_connection, user_id=TEST_USER_ID
        )

        assert await _count_sync_metadata(async_connection, source_id) == 0


class TestSyncMetadataRepoint:
    """The re-point method directly, against the database."""

    @pytest.mark.asyncio
    async def test_repoint_returns_collisions_and_clears_source(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
    ) -> None:
        survivor_id = await _make_contact(contact_repo, "Survivor")
        source_id = await _make_contact(contact_repo, "Source")
        await _add_sync_metadata(async_connection, survivor_id, "google", "people/surv")
        await _add_sync_metadata(async_connection, source_id, "google", "people/src")
        await _add_sync_metadata(async_connection, source_id, "immich", "person-uuid")

        repo = SyncMetadataRepository(async_connection)
        collisions = await repo.repoint_contact_links(
            source_id, survivor_id, async_connection
        )

        assert len(collisions) == 1
        assert collisions[0].external_system == "google"
        assert collisions[0].source_external_id == "people/src"
        assert collisions[0].survivor_external_id == "people/surv"
        # immich carried over; google collision removed; source has nothing left.
        assert await _linked_systems(async_connection, survivor_id) == {
            "google",
            "immich",
        }
        assert await _count_sync_metadata(async_connection, source_id) == 0
