"""Every integration that imports journals survives a merge without re-importing.

The guard for the rule "a sync never undoes a merge", run once per source in
the link-source registry. For each source that imports records it:

1. links two journals to two different records, the way that source's sync
   leaves them;
2. merges them in ``replace`` mode — the mode that drops a rival link;
3. checks the absorbed record is still the survivor's, live or as an alias;
4. replays the absorbed record through the sync processor, in the exact
   payload shape that source's worker sends, and checks nothing is created;
5. deletes the survivor and checks the absorbed record is sent upstream for
   deletion exactly when the survivor's own record is.

**Adding a source to ``JOURNAL_LINK_SOURCES`` fails this file** until it has a
seeder below, or is listed as outbound-only. That is the point: the question
"what happens to this integration's records when two journals merge?" has to
be answered for every integration, including ones that do not exist yet.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.journals import FitnessData, FitnessMergeMode
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.integrations.immich.album_outbox_event_processor import (
    EVENT_TYPE_IMMICH_ALBUM_CREATED,
    ImmichAlbumOutboxEventProcessor,
)
from app.core.integrations.link_sources import JOURNAL_LINK_SOURCES, AliasPolicy
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
    sync_event,
)

pytestmark = pytest.mark.integration

# Sources whose records are only ever pushed *to* the integration. The source
# journal's deletion undoes them upstream, so there is nothing to re-import.
OUTBOUND_ONLY_SOURCES = {"snipeit", "snipeit_checkout"}

# The JournalDeleted keys a worker acts on (Google's calendar cleanup and
# Snipe-IT's maintenance cleanup). Nothing consumes the others, so a record
# filed under them is not deleted upstream either way.
DELETE_KEYS_A_WORKER_CONSUMES = {"google", "snipeit_maintenance"}


@dataclass(frozen=True)
class SourceSeeder:
    """How one source's sync links a journal, and how its worker reports one.

    ``link`` leaves ``journal_id`` linked to ``record_id`` as the source's own
    sync does. ``replay`` sends ``record_id`` back through the processor in
    the worker's payload shape and returns the processor's result.
    ``payload_id`` is the id as that worker names it.
    """

    link: Callable[[AsyncConnection, int, str], Awaitable[None]]
    replay: Callable[[AsyncConnection, str], Awaitable[dict[str, Any]]]
    # Whether deleting a journal deletes its own record of this source
    # upstream: the absorbed record must follow, and the test must fail if
    # neither is sent rather than pass on "both missing".
    deleted_upstream: bool
    payload_id: Callable[[str], str] = lambda record_id: record_id
    # (survivor's record, absorbed record), in the shape the source issues.
    record_ids: tuple[str, str] = ("rec-own", "rec-absorbed")


async def _calendar(
    connection: AsyncConnection, source: str, google_calendar_id: str | None = None
) -> str:
    """The test's one calendar for ``source``."""
    calendar_id = uuid.uuid5(uuid.NAMESPACE_URL, f"merged-alias-guard/{source}")
    await connection.execute(
        text("""
            INSERT INTO calendars
                (id, user_id, name, color, integration_source, google_calendar_id)
            VALUES (:id, :user_id, :source, '#336699', :source, :google_id)
            ON CONFLICT (id) DO NOTHING
        """),
        {
            "id": calendar_id,
            "user_id": USER_ID,
            "source": source,
            "google_id": google_calendar_id,
        },
    )
    return str(calendar_id)


async def _event_link(
    connection: AsyncConnection, journal_id: int, calendar_id: str, event_id: str
) -> None:
    await connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id,
                 sync_capability, sync_status)
            VALUES (:journal_id, :calendar_id, :event_id, 'bidirectional', 'synced')
        """),
        {"journal_id": journal_id, "calendar_id": calendar_id, "event_id": event_id},
    )


async def _sync_row(
    connection: AsyncConnection, source: str, journal_id: int, record_id: str
) -> None:
    await SyncMetadataRepository(connection).upsert(
        user_id=USER_ID,
        integration_source=source,
        external_id=record_id,
        version_hash=f"hash-{record_id}",
        internal_id=journal_id,
        internal_entity_type="journal",
        external_entity_type="activity" if source == "strava" else "album",
    )


def _calendar_event_replay(
    source: str,
    payload_source: str,
    google_calendar_id: str | None = None,
    *,
    version_hash: Callable[[str], str] | None = None,
) -> Callable[[AsyncConnection, str], Awaitable[dict[str, Any]]]:
    async def replay(connection: AsyncConnection, payload_id: str) -> dict[str, Any]:
        event = sync_event(
            "journal_event.created",
            calendar_id=await _calendar(connection, source, google_calendar_id),
            external_event_id=payload_id,
        )
        event.event_data["integration_source"] = payload_source
        if version_hash is not None:
            event.event_data["journal_data"]["version_hash"] = version_hash(payload_id)
        return await build_processor(connection).process_event(event)

    return replay


async def _link_google(
    connection: AsyncConnection, journal_id: int, record: str
) -> None:
    calendar = await _calendar(connection, "google", "work@example.com")
    await _event_link(connection, journal_id, calendar, record)


async def _link_snipeit_import(
    connection: AsyncConnection, journal_id: int, record: str
) -> None:
    """The worker's sync row (naming no journal) plus the import link."""
    await SyncMetadataRepository(connection).upsert(
        user_id=USER_ID,
        integration_source="snipeit_maintenance",
        external_id=record,
        version_hash=_snipeit_hash(record),
    )
    calendar = await _calendar(connection, "snipeit_maintenance")
    await _event_link(connection, journal_id, calendar, record)


def _snipeit_hash(record: str) -> str:
    """The hash the worker sent last; an event carrying another is stale."""
    return f"snipeit-{record}"


async def _link_strava(
    connection: AsyncConnection, journal_id: int, record: str
) -> None:
    """Strava names an activity in three places; the merge must see one record."""
    await _sync_row(connection, "strava", journal_id, record)
    await SqlFitnessDataRepository(connection).save(
        FitnessData(journal_id=journal_id, distance=1000, strava_activity_id=record)
    )
    calendar = await _calendar(connection, "strava")
    await _event_link(connection, journal_id, calendar, f"strava:{record}")


async def _link_immich_album(
    connection: AsyncConnection, journal_id: int, record: str
) -> None:
    await _sync_row(connection, "immich_album", journal_id, record)


async def _replay_immich_album(
    connection: AsyncConnection, album_id: str
) -> dict[str, Any]:
    now = datetime.now(UTC)
    service = JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        task_anchor_repo=SqlTaskAnchorRepository(connection),
    )
    return await ImmichAlbumOutboxEventProcessor(
        journal_service=service, connection=connection
    ).process_event(
        OutboxEvent(
            id=uuid.uuid4(),
            event_type=EVENT_TYPE_IMMICH_ALBUM_CREATED,
            aggregate_id="0",
            event_data={
                "integration_source": "immich_album",
                "external_id": album_id,
                "version_hash": "v1",
                "sync_action": "created",
                "journal_data": {
                    "user_id": USER_ID,
                    "title": "Album",
                    "content": "",
                    "event_date_range_start": now.isoformat(),
                    "event_date_range_end": now.isoformat(),
                },
                "album_metadata": {"album_name": "Album", "asset_count": 1},
                "sync_timestamp": now.isoformat(),
            },
            occurred_at=now,
            retry_count=0,
        )
    )


SEEDERS: dict[str, SourceSeeder] = {
    "google_calendar": SourceSeeder(
        link=_link_google,
        replay=_calendar_event_replay("google", "google", "work@example.com"),
        deleted_upstream=True,
    ),
    "snipeit_maintenance": SourceSeeder(
        link=_link_snipeit_import,
        replay=_calendar_event_replay(
            "snipeit_maintenance", "snipeit_maintenance", version_hash=_snipeit_hash
        ),
        deleted_upstream=True,
        record_ids=("snipeit_maint:41", "snipeit_maint:42"),
    ),
    "strava": SourceSeeder(
        link=_link_strava,
        replay=_calendar_event_replay("strava", "strava"),
        deleted_upstream=False,
        payload_id=lambda record_id: f"strava:{record_id}",
        record_ids=("111", "222"),
    ),
    "immich_album": SourceSeeder(
        link=_link_immich_album,
        replay=_replay_immich_album,
        deleted_upstream=False,
    ),
}


def test_every_registered_source_has_answered_the_merge_question() -> None:
    """A new link source needs a seeder here, or a reason it cannot re-import."""
    assert set(JOURNAL_LINK_SOURCES) == set(SEEDERS) | OUTBOUND_ONLY_SOURCES


@pytest.mark.parametrize("source", sorted(OUTBOUND_ONLY_SOURCES))
def test_an_outbound_only_source_holds_no_inbound_records(source: str) -> None:
    stores = JOURNAL_LINK_SOURCES[source].stores
    assert AliasPolicy.INBOUND not in {store.alias_policy for store in stores}


async def _journal(connection: AsyncConnection, title: str) -> int:
    now = datetime.now(UTC)
    result = await connection.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, '', :now, :now)
            RETURNING id
        """),
        {"user_id": USER_ID, "title": title, "now": now},
    )
    return int(result.scalar_one())


async def _deletion_ids(connection: AsyncConnection, journal_id: int) -> set[str]:
    """Event ids a worker is told to delete upstream when the journal goes."""
    await JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        task_anchor_repo=SqlTaskAnchorRepository(connection),
    ).delete_journal(journal_id, connection)
    row = (
        await connection.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'JournalDeleted' AND aggregate_id = :journal_id
            """),
            {"journal_id": journal_id},
        )
    ).one()
    event_data = row.event_data
    if isinstance(event_data, str):
        event_data = json.loads(event_data)
    return {
        entry["external_event_id"]
        for key, entries in event_data["external_identifiers"].items()
        if key in DELETE_KEYS_A_WORKER_CONSUMES
        for entry in entries
    }


@pytest.mark.parametrize("source", sorted(SEEDERS))
async def test_a_replace_merge_never_lets_the_absorbed_record_back_in(
    source: str,
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    conn = async_connection
    seeder = SEEDERS[source]
    own, absorbed_record = seeder.record_ids
    survivor = await _journal(conn, "Survivor")
    absorbed = await _journal(conn, "Absorbed")
    await seeder.link(conn, survivor, own)
    await seeder.link(conn, absorbed, absorbed_record)

    await JournalMergeService(
        journal_repo=SqlJournalRepository(conn),
        event_publisher=OutboxEventPublisher(conn),
        task_merge_service=TaskJournalMergeService(
            task_anchor_repo=SqlTaskAnchorRepository(conn),
            event_publisher=OutboxEventPublisher(conn),
        ),
    ).merge_journals(
        survivor, absorbed, conn, fitness_merge_mode=FitnessMergeMode.REPLACE
    )

    # 3. The survivor still answers for the absorbed record.
    assert (
        await SqlJournalRepository(conn).find_id_by_external_id(
            USER_ID, source, absorbed_record
        )
        == survivor
    )

    # 4. Its sync coming round again creates nothing.
    result = await seeder.replay(conn, seeder.payload_id(absorbed_record))
    assert result["status"] == "skipped"
    assert result["journal_id"] == survivor
    count = await conn.execute(
        text("SELECT count(*) FROM journals WHERE user_id = :user_id"),
        {"user_id": USER_ID},
    )
    assert count.scalar_one() == 1

    # 5. Deleting the survivor treats the absorbed record as its own.
    deleted = await _deletion_ids(conn, survivor)
    assert (seeder.payload_id(own) in deleted) is seeder.deleted_upstream
    assert (seeder.payload_id(absorbed_record) in deleted) is seeder.deleted_upstream
