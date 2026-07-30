"""Integration tests for the incomplete outdoor activities projection.

Exercises the real ``SqlIncompleteOutdoorActivityRepository`` and the
``IncompleteOutdoorActivityService`` (with the real dismissal repository)
against Docker PostgreSQL. Each test seeds its own journals via the
repositories, so outcomes are deterministic.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    BushwalkingData,
    CanyoningData,
    EventDateRange,
    IncompletenessReason,
    Journal,
    KayakingData,
    SnorkellingData,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.incomplete_outdoor_activity_repository import (
    SqlIncompleteOutdoorActivityRepository,
)
from app.core.journal.adapters.sql.kayaking_data_repository import (
    SqlKayakingDataRepository,
)
from app.core.journal.adapters.sql.outdoor_activity_dismissal_repository import (
    SqlOutdoorActivityDismissalRepository,
)
from app.core.journal.adapters.sql.snorkelling_data_repository import (
    SqlSnorkellingDataRepository,
)
from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.journal.outdoor_activity_seeding import (
    OTHER_USER_ID,
    USER_ID,
    Seeder,
)


@pytest_asyncio.fixture
async def facts_repository(
    async_connection: AsyncConnection,
) -> SqlIncompleteOutdoorActivityRepository:
    return SqlIncompleteOutdoorActivityRepository(async_connection)


@pytest_asyncio.fixture
async def dismissal_repository(
    async_connection: AsyncConnection,
) -> SqlOutdoorActivityDismissalRepository:
    return SqlOutdoorActivityDismissalRepository(async_connection)


@pytest_asyncio.fixture
async def user_settings_repository(
    async_connection: AsyncConnection,
) -> SqlUserSettingsRepository:
    return SqlUserSettingsRepository(async_connection)


@pytest_asyncio.fixture
async def service(
    facts_repository: SqlIncompleteOutdoorActivityRepository,
    dismissal_repository: SqlOutdoorActivityDismissalRepository,
    user_settings_repository: SqlUserSettingsRepository,
) -> IncompleteOutdoorActivityService:
    return IncompleteOutdoorActivityService(
        facts_repo=facts_repository,
        dismissal_repo=dismissal_repository,
        user_settings_repo=user_settings_repository,
    )


@pytest_asyncio.fixture
async def seeder(async_connection: AsyncConnection) -> Seeder:
    return Seeder(async_connection)


@pytest.mark.integration
class TestIncompleteProjection:
    async def test_lists_journal_with_all_three_reasons(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        async_connection: AsyncConnection,
    ) -> None:
        """An empty canyoning journal matches every rule with all its reasons."""
        journal_id = await seeder.create_outdoor_journal(title="Empty canyon")
        # Dependency-added rows, all attribute-less, no template, no participants.
        await SqlBushwalkingDataRepository(async_connection).save(
            BushwalkingData(journal_id=journal_id)
        )
        await SqlAbseilingDataRepository(async_connection).save(
            AbseilingData(journal_id=journal_id)
        )
        await SqlCanyoningDataRepository(async_connection).save(
            CanyoningData(journal_id=journal_id)
        )

        result = await service.list_incomplete(USER_ID)

        assert [entry.journal_id for entry in result] == [journal_id]
        assert result[0].title == "Empty canyon"
        assert result[0].reasons == [
            IncompletenessReason.NO_ATTRIBUTES,
            IncompletenessReason.MISSING_TEMPLATE,
            IncompletenessReason.NO_PARTICIPANTS,
        ]

    async def test_complete_journal_not_listed(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await seeder.create_outdoor_journal(title="Kayak day")
        await SqlKayakingDataRepository(async_connection).save(
            KayakingData(journal_id=journal_id, water_type="river")
        )
        await seeder.add_participant(journal_id)

        result = await service.list_incomplete(USER_ID)

        assert result == []

    async def test_bushwalking_only_without_participants_not_listed(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        async_connection: AsyncConnection,
    ) -> None:
        """A solo hike with attributes set is complete despite no participants."""
        journal_id = await seeder.create_outdoor_journal(title="Solo hike")
        await SqlBushwalkingDataRepository(async_connection).save(
            BushwalkingData(journal_id=journal_id, track_grading="Grade 3")
        )

        result = await service.list_incomplete(USER_ID)

        assert result == []

    async def test_fieldless_snorkelling_journal_not_flagged_for_attributes(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        async_connection: AsyncConnection,
    ) -> None:
        """Snorkelling has no fillable fields, so only rule 3 can flag it."""
        journal_id = await seeder.create_outdoor_journal(title="Reef snorkel")
        await SqlSnorkellingDataRepository(async_connection).save(
            SnorkellingData(journal_id=journal_id)
        )

        result = await service.list_incomplete(USER_ID)

        assert [entry.journal_id for entry in result] == [journal_id]
        assert result[0].reasons == [IncompletenessReason.NO_PARTICIPANTS]

    async def test_dismissed_journal_excluded_and_undismiss_restores(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        dismissal_repository: SqlOutdoorActivityDismissalRepository,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await seeder.create_outdoor_journal(title="Kayak, no details")
        await SqlKayakingDataRepository(async_connection).save(
            KayakingData(journal_id=journal_id)
        )
        await seeder.add_participant(journal_id)

        await dismissal_repository.dismiss(
            journal_id=journal_id, user_id=USER_ID, provenance=Provenance.UI
        )
        assert await service.list_incomplete(USER_ID) == []

        await dismissal_repository.undismiss(journal_id=journal_id, user_id=USER_ID)
        restored = await service.list_incomplete(USER_ID)
        assert [entry.journal_id for entry in restored] == [journal_id]
        assert restored[0].reasons == [IncompletenessReason.NO_ATTRIBUTES]

    async def test_other_users_and_non_outdoor_journals_excluded(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        async_connection: AsyncConnection,
    ) -> None:
        # Another user's incomplete outdoor journal.
        other_journal_id = await seeder.create_outdoor_journal(
            title="Someone else's trip", user_id=OTHER_USER_ID
        )
        await SqlKayakingDataRepository(async_connection).save(
            KayakingData(journal_id=other_journal_id)
        )
        # A journal of this user with no outdoor_activity_data row at all.
        now = datetime.now(UTC)
        await seeder.journal_repo.save(
            Journal(
                user_id=USER_ID,
                title="Plain note",
                content="content",
                event_date_range=EventDateRange(start=now, end=now),
            )
        )

        assert await service.list_incomplete(USER_ID) == []

    async def test_facts_include_participant_and_pitch_counts(
        self,
        seeder: Seeder,
        facts_repository: SqlIncompleteOutdoorActivityRepository,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await seeder.create_outdoor_journal(title="Pitchy canyon")
        template_id = uuid4()
        await async_connection.execute(
            text(
                """
                INSERT INTO activity_templates (id, user_id, name, template_type)
                VALUES (:id, :user_id, :name, :template_type)
                """
            ),
            {
                "id": template_id,
                "user_id": USER_ID,
                "name": "Test Canyon",
                "template_type": "abseiling",
            },
        )
        await SqlAbseilingDataRepository(async_connection).save(
            AbseilingData(journal_id=journal_id, template_id=template_id)
        )
        pitch_repo = SqlAbseilPitchRepository(async_connection)
        await pitch_repo.save(AbseilPitch(journal_id=journal_id, pitch_number=1))
        await pitch_repo.save(AbseilPitch(journal_id=journal_id, pitch_number=2))
        await seeder.add_participant(journal_id)

        facts = await facts_repository.list_outdoor_activity_facts(USER_ID)

        assert len(facts) == 1
        assert facts[0].journal_id == journal_id
        assert facts[0].participant_count == 1
        assert facts[0].abseil_pitch_count == 2
        assert facts[0].abseiling_data is not None
        assert facts[0].abseiling_data.template_id is not None

    async def test_filling_the_gap_removes_entry(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        async_connection: AsyncConnection,
    ) -> None:
        """The list updates as data is filled in (spec: entry stops matching)."""
        journal_id = await seeder.create_outdoor_journal(title="Kayak to fix")
        kayaking_repo = SqlKayakingDataRepository(async_connection)
        await kayaking_repo.save(KayakingData(journal_id=journal_id))

        flagged = await service.list_incomplete(USER_ID)
        assert [entry.journal_id for entry in flagged] == [journal_id]
        assert flagged[0].reasons == [
            IncompletenessReason.NO_ATTRIBUTES,
            IncompletenessReason.NO_PARTICIPANTS,
        ]

        # Fill both gaps: set an attribute and add a participant.
        await kayaking_repo.save(
            KayakingData(journal_id=journal_id, water_type="river")
        )
        await seeder.add_participant(journal_id)

        assert await service.list_incomplete(USER_ID) == []

    async def test_future_activity_not_listed(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        async_connection: AsyncConnection,
    ) -> None:
        """A trip that has not started yet is a plan, not a review item."""
        now = datetime.now(UTC)
        past_id = await seeder.create_outdoor_journal(
            title="Kayak last week", start=now - timedelta(days=7)
        )
        future_id = await seeder.create_outdoor_journal(
            title="Kayak next week", start=now + timedelta(days=7)
        )
        kayaking_repo = SqlKayakingDataRepository(async_connection)
        await kayaking_repo.save(KayakingData(journal_id=past_id))
        await kayaking_repo.save(KayakingData(journal_id=future_id))

        result = await service.list_incomplete(USER_ID)
        assert [entry.journal_id for entry in result] == [past_id]

        with_dismissed = await service.list_incomplete(USER_ID, include_dismissed=True)
        assert [entry.journal_id for entry in with_dismissed] == [past_id]

    async def test_user_timezone_anchors_the_future_cutoff(
        self,
        seeder: Seeder,
        service: IncompleteOutdoorActivityService,
        user_settings_repository: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """The cutoff is the user's end-of-day, not UTC's."""
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        # 2026-07-30 23:00 AEST — still the anchor day for this user.
        today_id = await seeder.create_outdoor_journal(
            title="Late paddle", start=datetime(2026, 7, 30, 13, tzinfo=UTC)
        )
        # 2026-07-31 00:30 AEST — already tomorrow for this user.
        tomorrow_id = await seeder.create_outdoor_journal(
            title="Midnight paddle", start=datetime(2026, 7, 30, 14, 30, tzinfo=UTC)
        )
        kayaking_repo = SqlKayakingDataRepository(async_connection)
        await kayaking_repo.save(KayakingData(journal_id=today_id))
        await kayaking_repo.save(KayakingData(journal_id=tomorrow_id))

        result = await service.list_incomplete(USER_ID, anchor=date(2026, 7, 30))

        assert [entry.journal_id for entry in result] == [today_id]
