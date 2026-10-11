"""A merge keeps every inbound record it absorbs recognisable as the survivor.

Merging deletes the source journal, and with it any external link the merge
could not carry over: a second Google event in a calendar the survivor already
has a link in, a rival Strava activity in a replace merge, a second Snipe-IT
import on the synthetic maintenance calendar. A record that loses its link is
a record the next sync has never seen, so it is imported again as a new
journal — the merge undone by the sync.

These tests pin down the rule that stops that: whatever inbound record the
source held that does not survive as a live link on the target is kept as a
**merged alias** of the target. Records the integrations *push* (Snipe-IT
check-outs) are not inbound, and the source's own deletion undoes them, so
they are never aliased.
"""

import uuid
from datetime import datetime

import pytest
from core_shared.models.journals import (
    EventDateRange,
    FitnessData,
    FitnessMergeMode,
    Journal,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
)
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

USER_ID = "merge-alias-user"


def _merge_service(connection: AsyncConnection) -> JournalMergeService:
    return JournalMergeService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        task_merge_service=TaskJournalMergeService(
            task_anchor_repo=SqlTaskAnchorRepository(connection),
            event_publisher=OutboxEventPublisher(connection),
        ),
    )


async def _journal(connection: AsyncConnection, title: str) -> int:
    journal = await SqlJournalRepository(connection).save(
        Journal(
            id=None,
            user_id=USER_ID,
            title=title,
            content="",
            event_date_range=EventDateRange(
                start=datetime(2026, 9, 4, 2, 15),
                end=datetime(2026, 9, 4, 3, 15),
            ),
        )
    )
    assert journal.id is not None
    return journal.id


async def _calendar(
    connection: AsyncConnection,
    *,
    integration_source: str,
    google_calendar_id: str | None = None,
) -> str:
    calendar_id = uuid.uuid4()
    await connection.execute(
        text("""
            INSERT INTO calendars
                (id, user_id, name, color, integration_source, google_calendar_id)
            VALUES (:id, :user_id, 'Work', '#336699', :source, :google_id)
        """),
        {
            "id": calendar_id,
            "user_id": USER_ID,
            "source": integration_source,
            "google_id": google_calendar_id,
        },
    )
    return str(calendar_id)


async def _event_link(
    connection: AsyncConnection,
    *,
    journal_id: int,
    calendar_id: str,
    external_event_id: str,
    external_identity: str | None = None,
    recurring_event_id: str | None = None,
) -> None:
    await connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, sync_capability,
                 sync_status, external_identity, recurring_event_id)
            VALUES (:journal_id, :calendar_id, :external_event_id,
                    'bidirectional', 'synced', :identity, :recurring)
        """),
        {
            "journal_id": journal_id,
            "calendar_id": calendar_id,
            "external_event_id": external_event_id,
            "identity": external_identity,
            "recurring": recurring_event_id,
        },
    )


async def _sync_row(
    connection: AsyncConnection,
    *,
    journal_id: int,
    integration_source: str,
    external_id: str,
    external_entity_type: str,
) -> None:
    await SyncMetadataRepository(connection).upsert(
        user_id=USER_ID,
        integration_source=integration_source,
        external_id=external_id,
        version_hash=f"hash-{external_id}",
        internal_id=journal_id,
        internal_entity_type="journal",
        external_entity_type=external_entity_type,
    )


async def _strava_activity(
    connection: AsyncConnection,
    *,
    journal_id: int,
    activity_id: str,
    strava_calendar_id: str,
) -> None:
    """A Strava import as the processor leaves it: three places name it."""
    await _sync_row(
        connection,
        journal_id=journal_id,
        integration_source="strava",
        external_id=activity_id,
        external_entity_type="activity",
    )
    await SqlFitnessDataRepository(connection).save(
        FitnessData(
            journal_id=journal_id, distance=5000, strava_activity_id=activity_id
        )
    )
    await _event_link(
        connection,
        journal_id=journal_id,
        calendar_id=strava_calendar_id,
        external_event_id=f"strava:{activity_id}",
    )


async def _aliases(connection: AsyncConnection) -> list[tuple[object, ...]]:
    result = await connection.execute(
        text("""
            SELECT journal_id, integration_source, external_id,
                   CAST(calendar_id AS TEXT), external_identity, recurring_event_id
            FROM journal_merged_aliases
            WHERE user_id = :user_id
            ORDER BY integration_source, external_id
        """),
        {"user_id": USER_ID},
    )
    return [tuple(row) for row in result.fetchall()]


@pytest.mark.integration
class TestMergeKeepsAbsorbedRecordsAsAliases:
    async def test_a_second_google_event_in_the_same_calendar_becomes_an_alias(
        self, clean_database: AsyncConnection
    ) -> None:
        """The ticket's case: two Pilates series in one Work calendar.

        The survivor can hold only one link per calendar, so the absorbed
        occurrence used to be dropped and re-imported by the next sync.
        """
        conn = clean_database
        work = await _calendar(
            conn, integration_source="google", google_calendar_id="work@example.com"
        )
        target = await _journal(conn, "Pilates")
        source = await _journal(conn, "Pilates")
        await _event_link(
            conn,
            journal_id=target,
            calendar_id=work,
            external_event_id="63goti_20260904T021000Z",
        )
        await _event_link(
            conn,
            journal_id=source,
            calendar_id=work,
            external_event_id="dm1q_20260904T021500Z",
            external_identity="google:dm1q@google.com:20260904T021500Z",
            recurring_event_id="dm1q",
        )

        await _merge_service(conn).merge_journals(target, source, conn)

        assert await _aliases(conn) == [
            (
                target,
                "google_calendar",
                "dm1q_20260904T021500Z",
                work,
                "google:dm1q@google.com:20260904T021500Z",
                "dm1q",
            )
        ]
        live = await conn.execute(
            text(
                "SELECT external_event_id FROM journal_external_event_links "
                "WHERE journal_id = :id"
            ),
            {"id": target},
        )
        assert [row[0] for row in live.fetchall()] == ["63goti_20260904T021000Z"]

    async def test_a_link_in_another_calendar_moves_live_with_its_series_id(
        self, clean_database: AsyncConnection
    ) -> None:
        """A link that can move does, keeping the recurring id, and is no alias."""
        conn = clean_database
        work = await _calendar(
            conn, integration_source="google", google_calendar_id="work@example.com"
        )
        personal = await _calendar(
            conn, integration_source="google", google_calendar_id="me@example.com"
        )
        target = await _journal(conn, "Physio")
        source = await _journal(conn, "Physio")
        await _event_link(
            conn, journal_id=target, calendar_id=work, external_event_id="work-1"
        )
        await _event_link(
            conn,
            journal_id=source,
            calendar_id=personal,
            external_event_id="personal-1_20260904T021500Z",
            recurring_event_id="personal-1",
        )

        await _merge_service(conn).merge_journals(target, source, conn)

        assert await _aliases(conn) == []
        moved = await conn.execute(
            text(
                "SELECT recurring_event_id FROM journal_external_event_links "
                "WHERE journal_id = :id AND calendar_id = :calendar_id"
            ),
            {"id": target, "calendar_id": personal},
        )
        assert moved.scalar_one() == "personal-1"

    async def test_a_replace_merge_keeps_the_rival_strava_activity_as_one_alias(
        self, clean_database: AsyncConnection
    ) -> None:
        """Three stores name the activity; it is still one absorbed record."""
        conn = clean_database
        strava_calendar = await _calendar(conn, integration_source="strava")
        target = await _journal(conn, "Ride")
        source = await _journal(conn, "Ride re-import")
        await _strava_activity(
            conn,
            journal_id=target,
            activity_id="111",
            strava_calendar_id=strava_calendar,
        )
        await _strava_activity(
            conn,
            journal_id=source,
            activity_id="222",
            strava_calendar_id=strava_calendar,
        )

        await _merge_service(conn).merge_journals(
            target, source, conn, fitness_merge_mode=FitnessMergeMode.REPLACE
        )

        assert await _aliases(conn) == [(target, "strava", "222", None, None, None)]

    async def test_an_aliased_activity_keeps_no_live_link_on_the_survivor(
        self, clean_database: AsyncConnection
    ) -> None:
        """A record is the survivor's either live or as an alias, never both.

        The survivor's Strava id was typed in by hand, so it has no synthetic
        calendar link and the absorbed activity's one moves across untouched
        — while the replace merge drops its sync row as the rival it is. Left
        live, that link would route the absorbed activity's next webhook to
        the survivor and overwrite the metrics the merge chose to keep.
        """
        conn = clean_database
        strava_calendar = await _calendar(conn, integration_source="strava")
        target = await _journal(conn, "Ride")
        source = await _journal(conn, "Ride re-import")
        await SqlFitnessDataRepository(conn).save(
            FitnessData(journal_id=target, distance=5000, strava_activity_id="111")
        )
        await _strava_activity(
            conn,
            journal_id=source,
            activity_id="222",
            strava_calendar_id=strava_calendar,
        )

        await _merge_service(conn).merge_journals(
            target, source, conn, fitness_merge_mode=FitnessMergeMode.REPLACE
        )

        assert await _aliases(conn) == [(target, "strava", "222", None, None, None)]
        live = await conn.execute(
            text(
                "SELECT external_event_id FROM journal_external_event_links "
                "WHERE journal_id = :id"
            ),
            {"id": target},
        )
        assert live.fetchall() == []

    async def test_an_additive_merge_keeps_both_activities_live_and_aliases_none(
        self, clean_database: AsyncConnection
    ) -> None:
        conn = clean_database
        target = await _journal(conn, "Ride part 1")
        source = await _journal(conn, "Ride part 2")
        await _sync_row(
            conn,
            journal_id=target,
            integration_source="strava",
            external_id="111",
            external_entity_type="activity",
        )
        await _sync_row(
            conn,
            journal_id=source,
            integration_source="strava",
            external_id="222",
            external_entity_type="activity",
        )

        await _merge_service(conn).merge_journals(
            target, source, conn, fitness_merge_mode=FitnessMergeMode.ADDITIVE
        )

        assert await _aliases(conn) == []

    async def test_a_rival_immich_album_becomes_an_alias(
        self, clean_database: AsyncConnection
    ) -> None:
        conn = clean_database
        target = await _journal(conn, "Trip")
        source = await _journal(conn, "Trip photos")
        await _sync_row(
            conn,
            journal_id=target,
            integration_source="immich_album",
            external_id="album-a",
            external_entity_type="album",
        )
        await _sync_row(
            conn,
            journal_id=source,
            integration_source="immich_album",
            external_id="album-b",
            external_entity_type="album",
        )

        await _merge_service(conn).merge_journals(target, source, conn)

        assert await _aliases(conn) == [
            (target, "immich_album", "album-b", None, None, None)
        ]

    async def test_a_second_snipeit_import_becomes_an_alias_but_pushes_do_not(
        self, clean_database: AsyncConnection
    ) -> None:
        """Imports are inbound; a check-out pushed from the source is not.

        The source's deletion checks the pushed record in upstream, so keeping
        it as an alias would record something that no longer exists.
        """
        conn = clean_database
        maintenance = await _calendar(conn, integration_source="snipeit_maintenance")
        target = await _journal(conn, "Service")
        source = await _journal(conn, "Service")
        await _event_link(
            conn, journal_id=target, calendar_id=maintenance, external_event_id="41"
        )
        await _event_link(
            conn, journal_id=source, calendar_id=maintenance, external_event_id="42"
        )
        await SyncMetadataRepository(conn).upsert(
            user_id=USER_ID,
            integration_source="snipeit_checkout",
            external_id=f"snipeit_checkout:7:{source}",
            version_hash="h",
            internal_uuid=str(source),
            internal_entity_type="journal",
        )

        await _merge_service(conn).merge_journals(target, source, conn)

        assert await _aliases(conn) == [
            (target, "snipeit_maintenance", "42", maintenance, None, None)
        ]

    async def test_a_merge_of_a_merged_journal_carries_its_aliases(
        self, clean_database: AsyncConnection
    ) -> None:
        """A ← B, then C ← A: C answers for everything B and A held."""
        conn = clean_database
        work = await _calendar(
            conn, integration_source="google", google_calendar_id="work@example.com"
        )
        first = await _journal(conn, "Pilates")
        second = await _journal(conn, "Pilates")
        survivor = await _journal(conn, "Pilates")
        await _event_link(
            conn, journal_id=first, calendar_id=work, external_event_id="a"
        )
        await _event_link(
            conn, journal_id=second, calendar_id=work, external_event_id="b"
        )
        await _event_link(
            conn, journal_id=survivor, calendar_id=work, external_event_id="c"
        )
        service = _merge_service(conn)

        await service.merge_journals(first, second, conn)
        await service.merge_journals(survivor, first, conn)

        assert {(row[0], row[2]) for row in await _aliases(conn)} == {
            (survivor, "a"),
            (survivor, "b"),
        }
