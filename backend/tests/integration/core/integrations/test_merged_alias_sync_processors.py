"""A sync never undoes a merge: aliased records are left alone.

A merge keeps each record it absorbed but could not hold as a live link as a
merged alias of the survivor. The two processors that turn inbound records
into journals are where that has to hold — workers only check advisorily, and
a merge can land between a worker's read and the processor's write. So for an
aliased record, whatever shape the event arrives in, the processor must not
create a journal, re-link the survivor to it, or apply it to the survivor.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from core_shared.repositories.merged_alias_repository import (
    ExternalRecord,
    MergedAliasRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.immich.album_outbox_event_processor import (
    EVENT_TYPE_IMMICH_ALBUM_CREATED,
    EVENT_TYPE_IMMICH_ALBUM_UPDATED,
    ImmichAlbumOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
    create_calendar,
    sync_event,
)

pytestmark = pytest.mark.integration


async def _journal_ids(connection: AsyncConnection) -> list[int]:
    result = await connection.execute(
        text("SELECT id FROM journals WHERE user_id = :user_id ORDER BY id"),
        {"user_id": USER_ID},
    )
    return [int(row[0]) for row in result]


async def _survivor_in(
    connection: AsyncConnection, calendar_id: str, *, absorbed: str
) -> int:
    """A journal synced from ``63goti`` that absorbed ``absorbed`` by merging."""
    created = await build_processor(connection).process_event(
        sync_event(
            "journal_event.created",
            calendar_id=calendar_id,
            external_event_id="63goti",
            title="Pilates",
        )
    )
    survivor = int(created["journal_id"])
    await MergedAliasRepository(connection).record_aliases(
        journal_id=survivor,
        user_id=USER_ID,
        records=[
            ExternalRecord(
                integration_source="google_calendar",
                external_id=absorbed,
                calendar_id=uuid.UUID(calendar_id),
                external_identity="token-dm1q",
            )
        ],
    )
    return survivor


async def _links(connection: AsyncConnection, journal_id: int) -> list[Any]:
    result = await connection.execute(
        text(
            "SELECT calendar_id, external_event_id FROM journal_external_event_links "
            "WHERE journal_id = :id ORDER BY external_event_id"
        ),
        {"id": journal_id},
    )
    return [(str(row[0]), row[1]) for row in result]


async def _title(connection: AsyncConnection, journal_id: int) -> str:
    result = await connection.execute(
        text("SELECT title FROM journals WHERE id = :id"), {"id": journal_id}
    )
    return str(result.scalar_one())


class TestJournalSyncProcessorLeavesAliasesAlone:
    async def test_an_aliased_event_arriving_as_new_creates_nothing(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG002
    ) -> None:
        """The ticket's case: the absorbed occurrence syncs again."""
        work = await create_calendar(async_connection, name="Work")
        survivor = await _survivor_in(async_connection, work, absorbed="dm1q")

        result = await build_processor(async_connection).process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="dm1q",
                title="Pilates (old series)",
            )
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "merged_alias"
        assert result["journal_id"] == survivor
        assert await _journal_ids(async_connection) == [survivor]

    async def test_another_calendars_copy_of_an_aliased_event_creates_nothing(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG002
    ) -> None:
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")
        survivor = await _survivor_in(async_connection, work, absorbed="dm1q")

        result = await build_processor(async_connection).process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-of-dm1q",
                external_identity="token-dm1q",
            )
        )

        assert result["reason"] == "merged_alias"
        assert await _journal_ids(async_connection) == [survivor]
        assert await _links(async_connection, survivor) == [(work, "63goti")]

    async def test_an_update_routed_to_the_survivor_neither_relinks_nor_edits_it(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG002
    ) -> None:
        """Linking the survivor to the absorbed event would overwrite its link.

        The survivor already holds its one link in this calendar, and the
        link upsert replaces the event id on conflict — which would orphan the
        survivor's own event and have the sync import *that* next.
        """
        work = await create_calendar(async_connection, name="Work")
        survivor = await _survivor_in(async_connection, work, absorbed="dm1q")

        result = await build_processor(async_connection).process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=work,
                external_event_id="dm1q",
                existing_journal_id=survivor,
                title="Renamed in the old series",
                etag='"etag-2"',
            )
        )

        assert result["reason"] == "merged_alias"
        assert await _links(async_connection, survivor) == [(work, "63goti")]
        assert await _title(async_connection, survivor) == "Pilates"

    async def test_an_update_queued_for_the_absorbed_journal_is_skipped(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG002
    ) -> None:
        """Sent before the merge, it names a journal that no longer exists."""
        work = await create_calendar(async_connection, name="Work")
        survivor = await _survivor_in(async_connection, work, absorbed="dm1q")

        result = await build_processor(async_connection).process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=work,
                external_event_id="dm1q",
                existing_journal_id=survivor + 1000,
            )
        )

        assert result["reason"] == "merged_alias"
        assert await _journal_ids(async_connection) == [survivor]

    async def test_an_aliased_strava_activity_creates_nothing(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG002
    ) -> None:
        """Strava names its activity ``strava:<id>``; the alias holds ``<id>``."""
        strava_calendar = await create_calendar(async_connection, name="Strava")
        survivor = await _survivor_in(async_connection, strava_calendar, absorbed="x")
        await MergedAliasRepository(async_connection).record_aliases(
            journal_id=survivor,
            user_id=USER_ID,
            records=[ExternalRecord(integration_source="strava", external_id="222")],
        )
        event = sync_event(
            "journal_event.created",
            calendar_id=strava_calendar,
            external_event_id="strava:222",
        )
        event.event_data["integration_source"] = "strava"

        result = await build_processor(async_connection).process_event(event)

        assert result["reason"] == "merged_alias"
        assert await _journal_ids(async_connection) == [survivor]


def _album_processor(connection: AsyncConnection) -> ImmichAlbumOutboxEventProcessor:
    service = JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(connection),
        task_anchor_repo=SqlTaskAnchorRepository(connection),
    )
    return ImmichAlbumOutboxEventProcessor(
        journal_service=service, connection=connection
    )


def _album_event(event_type: str, album_id: str) -> OutboxEvent:
    now = datetime.now(UTC)
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        aggregate_id="0",
        event_data={
            "integration_source": "immich_album",
            "external_id": album_id,
            "version_hash": "v1",
            "sync_action": event_type.split(".")[1],
            "journal_data": {
                "user_id": USER_ID,
                "title": "Trip photos",
                "content": "",
                "event_date_range_start": now.isoformat(),
                "event_date_range_end": now.isoformat(),
            },
            "album_metadata": {"album_name": "Trip photos", "asset_count": 3},
            "sync_timestamp": now.isoformat(),
        },
        occurred_at=now,
        retry_count=0,
    )


class TestImmichAlbumProcessorLeavesAliasesAlone:
    @pytest.mark.parametrize(
        "event_type", [EVENT_TYPE_IMMICH_ALBUM_CREATED, EVENT_TYPE_IMMICH_ALBUM_UPDATED]
    )
    async def test_an_aliased_album_creates_nothing(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG002
        event_type: str,
    ) -> None:
        work = await create_calendar(async_connection, name="Work")
        survivor = await _survivor_in(async_connection, work, absorbed="x")
        await MergedAliasRepository(async_connection).record_aliases(
            journal_id=survivor,
            user_id=USER_ID,
            records=[
                ExternalRecord(integration_source="immich_album", external_id="album-b")
            ],
        )

        result = await _album_processor(async_connection).process_event(
            _album_event(event_type, "album-b")
        )

        assert result["reason"] == "merged_alias"
        assert result["journal_id"] == survivor
        assert await _journal_ids(async_connection) == [survivor]
