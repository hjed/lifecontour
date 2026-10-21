"""Inbound contact syncs overlapping local writes, against real PostgreSQL.

Issue #1735: the inbound ``contact.updated`` path read the stored contact
without its lock, kept the fields outside the sync's scope from that read, and
wrote them back - so a local edit committed in between was reverted. It also
took the sync link's lock *before* the contact's, the opposite order to a
contact merge, which locks both contacts and then repoints the link: overlap
the two and PostgreSQL aborts one as a deadlock.

Every row here is committed for real under a one-off owner (two connections
cannot share the savepoint fixture) and deleted afterwards, events included:
the services run on real connections, so what they publish is committed too.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from core_shared.models.contacts.sync_scope import ContactSyncField, ContactSyncScope
from core_shared.models.outbox import OutboxEvent
from core_shared.models.sync_metadata import SyncMetadata
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.contacts.adapters.sql import (
    SqlContactRelationshipRepository,
    SqlContactRepository,
)
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.integrations.outbox_event_processor import (
    OutboxEventProcessingError,
    OutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.tasks.adapters.sql.task_contact_repository import (
    SqlTaskContactRepository,
)
from app.core.tasks.services.task_contact_merge_service import TaskContactMergeService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    overlap,
    settle,
    wait_until_blocked_on_a_lock,
)
from tests.integration.contact_seeding import seed_contact
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

EXTERNAL_ID = "people/cRace"

# Google owns the names; it was never asked for the nickname.
NAMES_ONLY = ContactSyncScope(
    fields=frozenset({ContactSyncField.FIRST_NAME, ContactSyncField.LAST_NAME}),
    important_date_types=frozenset(),
)


@dataclass(frozen=True)
class Synced:
    user_id: str
    contact_id: int
    other_contact_id: int


@asynccontextmanager
async def synced_contacts(async_engine: AsyncEngine) -> AsyncIterator[Synced]:
    """Bob, linked to Google, and a second contact to merge him into."""
    user_id = f"race-{uuid4()}"
    async with async_engine.connect() as setup:
        contact_id = await seed_contact(
            setup,
            user_id=user_id,
            first_name="Robert",
            last_name="Smith",
            nick_name="Bob",
        )
        other_id = await seed_contact(setup, user_id=user_id, first_name="Roberta")
        await setup.execute(
            text(
                "INSERT INTO sync_metadata "
                "(user_id, internal_id, integration_source, external_id, "
                "last_synced_at, version_hash, sync_status, internal_entity_type, "
                "external_entity_type) "
                "VALUES (:u, :c, 'google', :eid, now(), 'etag-old', 'success', "
                "'contact', 'person')"
            ),
            {"u": user_id, "c": contact_id, "eid": EXTERNAL_ID},
        )
        await setup.commit()

    try:
        yield Synced(user_id, contact_id, other_id)
    finally:
        async with async_engine.connect() as cleanup:
            for statement in (
                "DELETE FROM outbox_events WHERE aggregate_id = ANY(:ids)",
                "DELETE FROM field_history WHERE user_id = :u",
                "DELETE FROM sync_metadata WHERE user_id = :u",
                "DELETE FROM contacts WHERE user_id = :u",
            ):
                await cleanup.execute(
                    text(statement), {"ids": [contact_id, other_id], "u": user_id}
                )
            await cleanup.commit()


def _google_update(user_id: str, etag: str = "etag-new") -> OutboxEvent:
    return OutboxEvent.create_contact_sync_event(
        contact_data={"user_id": user_id, "first_name": "Rob", "last_name": "Smith"},
        integration_source="google",
        external_id=EXTERNAL_ID,
        sync_type="updated",
        etag=etag,
        user_id=user_id,
        sync_scope=NAMES_ONLY,
    )


async def _process(connection: AsyncConnection, event: OutboxEvent) -> dict[str, Any]:
    """Process an event as the stream consumer does: one unit of work."""
    async with unit_of_work(connection):
        return await OutboxEventProcessor(
            build_contact_service(connection), connection
        ).process_event(event)


def _merge_service_on(connection: AsyncConnection) -> ContactMergeService:
    return ContactMergeService(
        contact_repo=SqlContactRepository(connection),
        relationship_repo=SqlContactRelationshipRepository(connection),
        journal_relationship_repo=SqlJournalContactRelationshipRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        history_repo=SqlFieldHistoryRepository(connection),
        sync_metadata_repo=SyncMetadataRepository(connection),
        task_merge_service=TaskContactMergeService(
            task_contact_repo=SqlTaskContactRepository(connection),
            event_publisher=OutboxEventPublisher(connection),
        ),
    )


async def _row(async_engine: AsyncEngine, contact_id: int) -> Any:
    async with async_engine.connect() as check:
        return (
            await check.execute(
                text("SELECT first_name, nick_name FROM contacts WHERE id = :id"),
                {"id": contact_id},
            )
        ).one_or_none()


async def _linked_contact(async_engine: AsyncEngine, user_id: str) -> int:
    async with async_engine.connect() as check:
        return int(
            (
                await check.execute(
                    text(
                        "SELECT internal_id FROM sync_metadata "
                        "WHERE user_id = :u AND external_id = :eid"
                    ),
                    {"u": user_id, "eid": EXTERNAL_ID},
                )
            ).scalar_one()
        )


@pytest.mark.integration
class TestInboundSyncOverlappingALocalEdit:
    async def test_a_local_edit_committed_first_is_not_reverted(
        self, async_engine: AsyncEngine
    ) -> None:
        async with synced_contacts(async_engine) as synced:

            async def local_edit(connection: AsyncConnection) -> None:
                await build_contact_service(connection).update_contact_field(
                    synced.contact_id,
                    "nick_name",
                    "Bobby",
                    connection,
                    user_id=synced.user_id,
                )

            async def inbound(connection: AsyncConnection) -> None:
                await _process(connection, _google_update(synced.user_id))

            await overlap(async_engine, local_edit, inbound)

            row = await _row(async_engine, synced.contact_id)
            assert (row.first_name, row.nick_name) == ("Rob", "Bobby")

    async def test_a_local_edit_made_during_an_inbound_update_lands_after_it(
        self, async_engine: AsyncEngine
    ) -> None:
        async with synced_contacts(async_engine) as synced:

            async def inbound(connection: AsyncConnection) -> None:
                await _process(connection, _google_update(synced.user_id))

            async def local_edit(connection: AsyncConnection) -> None:
                await build_contact_service(connection).update_contact_field(
                    synced.contact_id,
                    "nick_name",
                    "Bobby",
                    connection,
                    user_id=synced.user_id,
                )

            await overlap(async_engine, inbound, local_edit)

            row = await _row(async_engine, synced.contact_id)
            assert (row.first_name, row.nick_name) == ("Rob", "Bobby")

    async def test_a_reconciled_creation_keeps_a_local_edit_committed_first(
        self, async_engine: AsyncEngine
    ) -> None:
        """The created-then-matched-by-email path had the same unlocked read."""
        async with synced_contacts(async_engine) as synced:
            async with async_engine.connect() as setup:
                await setup.execute(
                    text(
                        "INSERT INTO contact_methods "
                        "(contact_id, method_type, value, is_primary) "
                        "VALUES (:c, 'email', 'roberta@example.com', true)"
                    ),
                    {"c": synced.other_contact_id},
                )
                await setup.commit()
            created = OutboxEvent.create_contact_sync_event(
                contact_data={
                    "user_id": synced.user_id,
                    "first_name": "Bobbie",
                    "methods": [
                        {
                            "method_type": "email",
                            "value": "roberta@example.com",
                            "is_primary": True,
                        }
                    ],
                },
                integration_source="google",
                external_id="people/cRaceNew",
                sync_type="created",
                etag="etag-created",
                user_id=synced.user_id,
                sync_scope=NAMES_ONLY,
            )

            async def local_edit(connection: AsyncConnection) -> None:
                await build_contact_service(connection).update_contact_field(
                    synced.other_contact_id,
                    "nick_name",
                    "Bertie",
                    connection,
                    user_id=synced.user_id,
                )

            async def inbound(connection: AsyncConnection) -> None:
                result = await _process(connection, created)
                assert result["contact_id"] == synced.other_contact_id

            await overlap(async_engine, local_edit, inbound)

            row = await _row(async_engine, synced.other_contact_id)
            assert (row.first_name, row.nick_name) == ("Bobbie", "Bertie")


@pytest.mark.integration
class TestInboundSyncOverlappingAMerge:
    async def test_an_inbound_update_and_a_merge_queue_rather_than_deadlock(
        self, async_engine: AsyncEngine
    ) -> None:
        """The inbound update goes first, holding every lock it takes.

        Under the old order it held only the link at this point; the merge then
        took both contacts and waited on the link, the update waited on the
        contact, and PostgreSQL aborted one of them.
        """
        async with synced_contacts(async_engine) as synced:
            holding = asyncio.Event()
            release = asyncio.Event()

            class _PausingSyncMetadataRepository(SyncMetadataRepository):
                async def find_and_lock(
                    self, integration_source: str, external_id: str, *, user_id: str
                ) -> SyncMetadata | None:
                    found = await super().find_and_lock(
                        integration_source, external_id, user_id=user_id
                    )
                    holding.set()
                    await release.wait()
                    return found

            async def inbound() -> None:
                async with async_engine.connect() as connection:
                    async with unit_of_work(connection):
                        processor = OutboxEventProcessor(
                            build_contact_service(connection), connection
                        )
                        processor.sync_metadata_repo = _PausingSyncMetadataRepository(
                            connection
                        )
                        await processor.process_event(_google_update(synced.user_id))

            async def merge(connection: AsyncConnection) -> None:
                await _merge_service_on(connection).merge_contacts(
                    synced.other_contact_id,
                    synced.contact_id,
                    transaction=connection,
                    user_id=synced.user_id,
                )

            async with async_engine.connect() as merging_connection:
                merging_pid = await backend_pid(merging_connection)
                updating = asyncio.create_task(inbound())
                merging: asyncio.Task[None] | None = None
                try:
                    await bounded(holding.wait())
                    merging = asyncio.create_task(merge(merging_connection))
                    await wait_until_blocked_on_a_lock(async_engine, merging_pid)
                    release.set()
                    await bounded(asyncio.gather(updating, merging))
                finally:
                    # On a timeout, the paused update would hold its locks and
                    # the clean-up below would wait on them forever.
                    release.set()
                    await settle(updating, merging)

            assert await _row(async_engine, synced.contact_id) is None
            assert await _linked_contact(async_engine, synced.user_id) == (
                synced.other_contact_id
            )

    async def test_an_update_for_a_contact_merged_away_meanwhile_is_retried(
        self, async_engine: AsyncEngine
    ) -> None:
        """The merge goes first; the update finds its contact gone.

        It must fail as a transient error - redelivered, it resolves the link
        again and lands on the survivor - never create a contact or give up.
        """
        async with synced_contacts(async_engine) as synced:

            async def merge(connection: AsyncConnection) -> None:
                await _merge_service_on(connection).merge_contacts(
                    synced.other_contact_id,
                    synced.contact_id,
                    transaction=connection,
                    user_id=synced.user_id,
                )

            update = _google_update(synced.user_id)

            async def inbound(connection: AsyncConnection) -> None:
                with pytest.raises(OutboxEventProcessingError) as failed:
                    await _process(connection, update)
                assert type(failed.value) is OutboxEventProcessingError

            await overlap(async_engine, merge, inbound)

            async with async_engine.connect() as redelivery:
                result = await _process(redelivery, _google_update(synced.user_id))

            assert result["contact_id"] == synced.other_contact_id
            assert (
                await _row(async_engine, synced.other_contact_id)
            ).first_name == "Rob"
