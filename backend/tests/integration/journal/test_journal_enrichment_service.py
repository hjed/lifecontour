"""Integration tests for JournalEnrichmentService against real Postgres.

The service is the one read REST and MCP both build a journal's payload from,
so these tests pin what that payload holds: which types, which type-data rows,
which contacts (and how their names read), tags, series and calendars.
"""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalType,
    MoodData,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.canoeing_data_repository import (
    SqlCanoeingDataRepository,
)
from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.caving_data_repository import (
    SqlCavingDataRepository,
)
from app.core.journal.adapters.sql.climbing_data_repository import (
    SqlClimbingDataRepository,
)
from app.core.journal.adapters.sql.cross_country_skiing_data_repository import (
    SqlCrossCountrySkiingDataRepository,
)
from app.core.journal.adapters.sql.diving_data_repository import (
    SqlDivingDataRepository,
)
from app.core.journal.adapters.sql.downhill_skiing_data_repository import (
    SqlDownhillSkiingDataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.gear_maintenance_data_repository import (
    SqlGearMaintenanceDataRepository,
)
from app.core.journal.adapters.sql.gear_usage_data_repository import (
    SqlGearUsageDataRepository,
)
from app.core.journal.adapters.sql.jogging_data_repository import (
    SqlJoggingDataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.adapters.sql.kayaking_data_repository import (
    SqlKayakingDataRepository,
)
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.adapters.sql.outdoor_planning_data_repository import (
    SqlOutdoorPlanningDataRepository,
)
from app.core.journal.adapters.sql.outdoor_training_data_repository import (
    SqlOutdoorTrainingDataRepository,
)
from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository
from app.core.journal.adapters.sql.snorkelling_data_repository import (
    SqlSnorkellingDataRepository,
)
from app.core.journal.adapters.sql.travel_data_repository import (
    SqlTravelDataRepository,
)
from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.journal_enrichment_service import (
    JournalEnrichmentService,
    JournalTypeDataRepositories,
)
from tests.integration.contact_seeding import seed_contact
from tests.integration.linked_calendar_seeding import (
    USER_ID,
    create_calendar,
    create_event_journal,
    link_calendar,
)

OTHER_USER_ID = "someone-else-456"


def _service(conn: AsyncConnection) -> JournalEnrichmentService:
    return JournalEnrichmentService(
        type_data_repos=JournalTypeDataRepositories(
            calendar_info_repo=SqlCalendarInfoRepository(conn),
            mood_data_repo=SqlMoodDataRepository(conn),
            plan_data_repo=SqlPlanDataRepository(conn),
            travel_data_repo=SqlTravelDataRepository(conn),
            photo_album_data_repo=AlbumSyncReadRepository(conn),
            fitness_data_repo=SqlFitnessDataRepository(conn),
            outdoor_activity_data_repo=SqlOutdoorActivityDataRepository(conn),
            bushwalking_data_repo=SqlBushwalkingDataRepository(conn),
            jogging_data_repo=SqlJoggingDataRepository(conn),
            abseiling_data_repo=SqlAbseilingDataRepository(conn),
            caving_data_repo=SqlCavingDataRepository(conn),
            canyoning_data_repo=SqlCanyoningDataRepository(conn),
            climbing_data_repo=SqlClimbingDataRepository(conn),
            kayaking_data_repo=SqlKayakingDataRepository(conn),
            cross_country_skiing_data_repo=SqlCrossCountrySkiingDataRepository(conn),
            canoeing_data_repo=SqlCanoeingDataRepository(conn),
            snorkelling_data_repo=SqlSnorkellingDataRepository(conn),
            diving_data_repo=SqlDivingDataRepository(conn),
            downhill_skiing_data_repo=SqlDownhillSkiingDataRepository(conn),
            outdoor_planning_data_repo=SqlOutdoorPlanningDataRepository(conn),
            outdoor_training_data_repo=SqlOutdoorTrainingDataRepository(conn),
            gear_maintenance_data_repo=SqlGearMaintenanceDataRepository(conn),
            gear_usage_data_repo=SqlGearUsageDataRepository(conn),
            abseil_pitch_repo=SqlAbseilPitchRepository(conn),
        ),
        journal_repo=SqlJournalRepository(conn),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(conn),
        contact_repo=SqlContactRepository(conn),
        tag_repo=SqlJournalTagRepository(conn),
        series_repo=SqlJournalSeriesRepository(conn),
        calendar_repo=SqlCalendarRepository(conn),
    )


async def _create_journal(
    conn: AsyncConnection, title: str = "A note", user_id: str = USER_ID
) -> int:
    start = datetime.now(UTC) - timedelta(days=1)
    result = await conn.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content,
                 event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, '', :start, :end)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "title": title,
            "start": start,
            "end": start + timedelta(hours=1),
        },
    )
    return int(result.scalar_one())


async def _mark_photo_album(conn: AsyncConnection, journal_id: int) -> None:
    await AlbumSyncReadRepository(conn).upsert_link(
        journal_id,
        "album-1",
        {"album_name": "Trip"},
        version_hash="hash",
        bump_anchor=True,
    )


@pytest.mark.integration
class TestEnrichTypes:
    async def test_untyped_journal_is_a_note(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        assert enrichment.types == [JournalType.NOTE.value]
        assert enrichment.type_rows == {}

    async def test_type_rows_follow_reader_order(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)
        await SqlAbseilingDataRepository(async_connection).save(
            AbseilingData(journal_id=journal_id, number_of_abseils=2)
        )
        await SqlMoodDataRepository(async_connection).save(
            MoodData(journal_id=journal_id, mood_value=7)
        )

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        assert enrichment.types == [
            JournalType.MOOD_RATING.value,
            JournalType.ABSEILING_TRIP.value,
        ]
        mood = enrichment.type_rows[JournalType.MOOD_RATING]
        assert isinstance(mood, MoodData)
        assert mood.mood_value == 7

    async def test_abseil_pitches_are_loaded_in_order(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)
        await SqlAbseilingDataRepository(async_connection).save(
            AbseilingData(journal_id=journal_id)
        )
        pitch_repo = SqlAbseilPitchRepository(async_connection)
        await pitch_repo.save(AbseilPitch(journal_id=journal_id, pitch_number=2))
        await pitch_repo.save(AbseilPitch(journal_id=journal_id, pitch_number=1))

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        assert [p.pitch_number for p in enrichment.abseil_pitches] == [1, 2]

    async def test_journal_without_abseiling_has_no_pitches(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        assert enrichment.abseil_pitches == []


@pytest.mark.integration
class TestEnrichContacts:
    async def test_contacts_carry_null_safe_names(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)
        full = await seed_contact(
            async_connection,
            first_name="Jane",
            last_name="Citizen",
            photo_url="https://example.test/jane.png",
        )
        first_only = await seed_contact(async_connection, first_name="Sam")
        rel_repo = SqlJournalContactRelationshipRepository(async_connection)
        for contact_id in (full, first_only):
            await rel_repo.create(
                JournalContactRelationship(
                    journal_id=journal_id,
                    contact_id=contact_id,
                    relationship_type=JournalContactRelationshipType.MENTION,
                )
            )

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        by_id = {c.contact_id: c for c in enrichment.contacts}
        assert by_id[full].name == "Jane Citizen"
        assert by_id[full].first_name == "Jane"
        assert by_id[full].last_name == "Citizen"
        assert by_id[full].photo_url == "https://example.test/jane.png"
        assert by_id[first_only].name == "Sam"
        assert by_id[first_only].last_name is None
        assert by_id[full].relationship.relationship_type == (
            JournalContactRelationshipType.MENTION
        )


@pytest.mark.integration
class TestEnrichTagsSeriesCalendars:
    async def test_tags_are_the_journals_tags(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)
        tag_repo = SqlJournalTagRepository(async_connection)
        tag = await tag_repo.save(JournalTag(name="enrichment-test-tag"))
        await tag_repo.save(JournalTag(name="unrelated-tag"))
        assert tag.id is not None
        await tag_repo.assign_tag(journal_id, tag.id)

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        assert [t.name for t in enrichment.tags] == ["enrichment-test-tag"]

    async def test_series_are_scoped_to_the_owner(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)
        series_repo = SqlJournalSeriesRepository(async_connection)
        series = await series_repo.save(JournalSeries(name="Weekly", user_id=USER_ID))
        assert series.id is not None
        await series_repo.add_member(series.id, journal_id)

        own = await _service(async_connection).enrich(journal_id, USER_ID)
        other = await _service(async_connection).enrich(journal_id, OTHER_USER_ID)

        assert [s.name for s in own.series] == ["Weekly"]
        assert other.series == []

    async def test_event_lists_every_calendar_holding_it(
        self, async_connection: AsyncConnection
    ) -> None:
        work = await create_calendar(async_connection, "Work")
        personal = await create_calendar(async_connection, "Personal")
        journal_id = await create_event_journal(
            async_connection, title="Physio", display_calendar_id=work
        )
        await link_calendar(
            async_connection,
            journal_id=journal_id,
            calendar_id=personal,
            external_event_id="personal-copy",
        )

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        assert JournalType.EVENT.value in enrichment.types
        assert [str(c.id) for c in enrichment.calendars] == [work, personal]

    async def test_non_event_with_a_stray_event_link_has_no_calendars(
        self, async_connection: AsyncConnection
    ) -> None:
        """Calendars belong to the EVENT type: no calendar_info row, no calendars.

        A merge moves external event links independently of type data, so a
        journal can hold a link without being an event.
        """
        calendar = await create_calendar(async_connection, "Work")
        journal_id = await _create_journal(async_connection)
        await link_calendar(
            async_connection,
            journal_id=journal_id,
            calendar_id=calendar,
            external_event_id="stray-link",
        )

        enrichment = await _service(async_connection).enrich(journal_id, USER_ID)

        assert enrichment.types == [JournalType.NOTE.value]
        assert enrichment.calendars == []


@pytest.mark.integration
class TestTypesFor:
    async def test_types_for_reports_each_journal_in_reader_order(
        self, async_connection: AsyncConnection
    ) -> None:
        note_id = await _create_journal(async_connection, "Plain")
        typed_id = await _create_journal(async_connection, "Typed")
        await SqlAbseilingDataRepository(async_connection).save(
            AbseilingData(journal_id=typed_id)
        )
        await SqlMoodDataRepository(async_connection).save(
            MoodData(journal_id=typed_id, mood_value=5)
        )
        await _mark_photo_album(async_connection, typed_id)

        types = await _service(async_connection).types_for([note_id, typed_id])

        assert types == {
            note_id: [JournalType.NOTE.value],
            typed_id: [
                JournalType.MOOD_RATING.value,
                JournalType.PHOTO_ALBUM.value,
                JournalType.ABSEILING_TRIP.value,
            ],
        }

    async def test_types_for_agrees_with_enrich(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _create_journal(async_connection)
        await _mark_photo_album(async_connection, journal_id)
        await SqlMoodDataRepository(async_connection).save(
            MoodData(journal_id=journal_id, mood_value=3)
        )
        service = _service(async_connection)

        enrichment = await service.enrich(journal_id, USER_ID)
        types = await service.types_for([journal_id])

        assert types[journal_id] == enrichment.types

    async def test_types_for_no_ids_runs_no_query(
        self, async_connection: AsyncConnection
    ) -> None:
        assert await _service(async_connection).types_for([]) == {}
