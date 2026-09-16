"""Integration tests for ``SqlActivityStatsRepository`` and route usage history.

Every read is scoped to one user and counts only journals with fitness data.
Each test seeds its own journals through the real repositories, so the rows it
reads are exactly the ones it expects.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    BushwalkingData,
    CanyoningData,
    EventDateRange,
    FitnessData,
    JoggingData,
    Journal,
    KayakingData,
    OutdoorActivityData,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.activity_stats_repository import (
    SqlActivityStatsRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.jogging_data_repository import (
    SqlJoggingDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.kayaking_data_repository import (
    SqlKayakingDataRepository,
)
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.models.activity_stats import (
    ActivityFilters,
    ActivityMetric,
    ActivityPersonalRecordRow,
    ActivityTotalsRow,
    ActivityTypeTotalsRow,
    TrendInterval,
)
from tests.integration.journal.outdoor_activity_seeding import (
    OTHER_USER_ID,
    USER_ID,
    Seeder,
)


@dataclass(frozen=True)
class Metrics:
    distance: int
    duration: int
    elevation_gain: int
    calories: int


class ActivitySeeder:
    """Seeds activity journals: a journal, its fitness row and subtype rows."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection
        self.seeder = Seeder(connection)

    async def fitness_journal(
        self,
        *,
        title: str,
        start: datetime,
        metrics: Metrics,
        user_id: str = USER_ID,
        content: str = "content",
    ) -> int:
        journal = await SqlJournalRepository(self.connection).save(
            Journal(
                user_id=user_id,
                title=title,
                content=content,
                event_date_range=EventDateRange(
                    start=start, end=start + timedelta(hours=2)
                ),
            )
        )
        assert journal.id is not None
        journal_id = journal.id
        await SqlFitnessDataRepository(self.connection).save(
            FitnessData(
                journal_id=journal_id,
                distance=metrics.distance,
                duration=metrics.duration,
                elevation_gain=metrics.elevation_gain,
                calories=metrics.calories,
            )
        )
        return journal_id

    async def kayaking_journal(
        self, *, title: str, start: datetime, metrics: Metrics, user_id: str = USER_ID
    ) -> int:
        journal_id = await self.fitness_journal(
            title=title, start=start, metrics=metrics, user_id=user_id
        )
        await SqlOutdoorActivityDataRepository(self.connection).save(
            OutdoorActivityData(journal_id=journal_id)
        )
        await SqlKayakingDataRepository(self.connection).save(
            KayakingData(journal_id=journal_id, water_type="river")
        )
        return journal_id

    async def jogging_journal(
        self, *, title: str, start: datetime, metrics: Metrics
    ) -> int:
        journal_id = await self.fitness_journal(
            title=title, start=start, metrics=metrics
        )
        await SqlJoggingDataRepository(self.connection).save(
            JoggingData(journal_id=journal_id)
        )
        return journal_id

    async def canyoning_journal(
        self, *, title: str, start: datetime, metrics: Metrics
    ) -> int:
        """A canyoning trip, which also carries bushwalking and outdoor rows."""
        journal_id = await self.fitness_journal(
            title=title, start=start, metrics=metrics
        )
        await SqlOutdoorActivityDataRepository(self.connection).save(
            OutdoorActivityData(journal_id=journal_id)
        )
        await SqlBushwalkingDataRepository(self.connection).save(
            BushwalkingData(journal_id=journal_id)
        )
        await SqlCanyoningDataRepository(self.connection).save(
            CanyoningData(journal_id=journal_id)
        )
        return journal_id


@dataclass(frozen=True)
class SeededActivities:
    kayak_id: int
    jog_id: int
    gym_id: int


@pytest_asyncio.fixture
async def repository(async_connection: AsyncConnection) -> SqlActivityStatsRepository:
    return SqlActivityStatsRepository(async_connection)


@pytest_asyncio.fixture
async def activities(async_connection: AsyncConnection) -> ActivitySeeder:
    return ActivitySeeder(async_connection)


@pytest_asyncio.fixture
async def seeded(activities: ActivitySeeder) -> SeededActivities:
    """Three of the user's activities in March–April 2024, plus rows to ignore.

    Another user's kayak and the user's own journal without fitness data must
    never be counted.
    """
    kayak_id = await activities.kayaking_journal(
        title="River paddle",
        start=datetime(2024, 3, 1, 9, tzinfo=UTC),
        metrics=Metrics(distance=12, duration=70, elevation_gain=20, calories=700),
    )
    jog_id = await activities.jogging_journal(
        title="Tempo run",
        start=datetime(2024, 3, 15, 7, tzinfo=UTC),
        metrics=Metrics(distance=8, duration=40, elevation_gain=110, calories=500),
    )
    gym_id = await activities.fitness_journal(
        title="Gym session",
        content="Treadmill intervals",
        start=datetime(2024, 4, 2, 18, tzinfo=UTC),
        metrics=Metrics(distance=5, duration=30, elevation_gain=0, calories=300),
    )
    await activities.kayaking_journal(
        title="Someone else's paddle",
        user_id=OTHER_USER_ID,
        start=datetime(2024, 3, 2, 9, tzinfo=UTC),
        metrics=Metrics(distance=99, duration=999, elevation_gain=999, calories=9999),
    )
    await activities.seeder.create_journal(
        title="Plain note", start=datetime(2024, 3, 3, tzinfo=UTC)
    )
    return SeededActivities(kayak_id=kayak_id, jog_id=jog_id, gym_id=gym_id)


def _filters(
    *,
    activity_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    search_query: str | None = None,
) -> ActivityFilters:
    return ActivityFilters(
        user_id=USER_ID,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
        search_query=search_query,
    )


@pytest.mark.integration
class TestListActivityJournals:
    async def test_lists_the_users_fitness_journals_newest_first(
        self, repository: SqlActivityStatsRepository, seeded: SeededActivities
    ) -> None:
        rows = await repository.list_activity_journals(_filters())

        assert [(row.journal.id, row.activity_type) for row in rows] == [
            (seeded.gym_id, "fitness"),
            (seeded.jog_id, "jogging"),
            (seeded.kayak_id, "kayaking"),
        ]
        kayak = rows[2]
        assert kayak.journal.title == "River paddle"
        assert kayak.journal.user_id == USER_ID
        assert (
            kayak.distance,
            kayak.duration,
            kayak.elevation_gain,
            kayak.calories,
        ) == (12, 70, 20, 700)

    async def test_most_specific_subtype_is_the_effective_type(
        self, repository: SqlActivityStatsRepository, activities: ActivitySeeder
    ) -> None:
        canyon_id = await activities.canyoning_journal(
            title="Canyon trip",
            start=datetime(2024, 5, 1, tzinfo=UTC),
            metrics=Metrics(distance=6, duration=300, elevation_gain=400, calories=900),
        )

        rows = await repository.list_activity_journals(
            _filters(activity_type="canyoning")
        )

        assert [(row.journal.id, row.activity_type) for row in rows] == [
            (canyon_id, "canyoning")
        ]

    async def test_filters_by_overlapping_dates_and_text(
        self, repository: SqlActivityStatsRepository, seeded: SeededActivities
    ) -> None:
        in_march = await repository.list_activity_journals(
            _filters(
                start_date=datetime(2024, 3, 10, tzinfo=UTC),
                end_date=datetime(2024, 3, 31, 23, 59, tzinfo=UTC),
            )
        )
        by_content = await repository.list_activity_journals(
            _filters(search_query="treadmill")
        )

        assert [row.journal.id for row in in_march] == [seeded.jog_id]
        assert [row.journal.id for row in by_content] == [seeded.gym_id]

    async def test_pages_while_count_covers_every_match(
        self, repository: SqlActivityStatsRepository, seeded: SeededActivities
    ) -> None:
        page = await repository.list_activity_journals(_filters(), limit=1, offset=1)
        total = await repository.count_activity_journals(_filters())

        assert [row.journal.id for row in page] == [seeded.jog_id]
        assert total == 3


@pytest.mark.integration
class TestActivityAggregates:
    @pytest.mark.usefixtures("seeded")
    async def test_overall_totals(self, repository: SqlActivityStatsRepository) -> None:
        assert await repository.get_totals(_filters()) == ActivityTotalsRow(
            total_activities=3,
            total_distance=25,
            total_duration=140,
            total_elevation_gain=130,
            total_calories=1500,
        )

    async def test_overall_totals_are_zero_without_activities(
        self, repository: SqlActivityStatsRepository
    ) -> None:
        assert await repository.get_totals(_filters()) == ActivityTotalsRow(
            total_activities=0,
            total_distance=0,
            total_duration=0,
            total_elevation_gain=0,
            total_calories=0,
        )

    @pytest.mark.usefixtures("seeded")
    async def test_totals_by_type_in_type_order(
        self, repository: SqlActivityStatsRepository
    ) -> None:
        rows = await repository.list_type_totals(_filters())

        assert rows == [
            ActivityTypeTotalsRow("fitness", 1, 5, 30, 0, 300),
            ActivityTypeTotalsRow("jogging", 1, 8, 40, 110, 500),
            ActivityTypeTotalsRow("kayaking", 1, 12, 70, 20, 700),
        ]

    async def test_personal_record_per_metric(
        self, repository: SqlActivityStatsRepository, seeded: SeededActivities
    ) -> None:
        longest = await repository.find_personal_record(
            _filters(), ActivityMetric.DISTANCE
        )
        highest = await repository.find_personal_record(
            _filters(), ActivityMetric.ELEVATION_GAIN
        )

        assert longest == ActivityPersonalRecordRow(
            activity_type="kayaking",
            journal_id=seeded.kayak_id,
            journal_title="River paddle",
            value=12,
        )
        assert highest is not None
        assert (highest.journal_id, highest.value) == (seeded.jog_id, 110)

    async def test_no_personal_record_without_activities(
        self, repository: SqlActivityStatsRepository
    ) -> None:
        assert (
            await repository.find_personal_record(_filters(), ActivityMetric.CALORIES)
            is None
        )

    @pytest.mark.usefixtures("seeded")
    async def test_monthly_trend_buckets(
        self, repository: SqlActivityStatsRepository
    ) -> None:
        rows = await repository.list_trend_buckets(_filters(), TrendInterval.MONTH)

        assert [
            (row.period_start, row.activity_count, row.total_distance) for row in rows
        ] == [
            (date(2024, 3, 1), 2, 20),
            (date(2024, 4, 1), 1, 5),
        ]
        assert (rows[0].total_duration, rows[0].total_elevation_gain) == (110, 130)

    @pytest.mark.usefixtures("seeded")
    async def test_aggregates_respect_the_activity_type_filter(
        self, repository: SqlActivityStatsRepository
    ) -> None:
        totals = await repository.get_totals(_filters(activity_type="jogging"))

        assert (totals.total_activities, totals.total_distance) == (1, 8)


@pytest.mark.integration
class TestRouteUsageHistory:
    async def test_route_usage_carries_the_journal_and_its_fitness_metrics(
        self, async_connection: AsyncConnection, seeded: SeededActivities
    ) -> None:
        seeder = Seeder(async_connection)
        route_id = await seeder.create_route(journal_id=seeded.kayak_id)

        rows = await SqlRouteRepository(async_connection).find_usage_history(
            USER_ID, route_id
        )

        assert len(rows) == 1
        usage = rows[0]
        assert (usage.journal_id, usage.journal_title, usage.activity_type) == (
            seeded.kayak_id,
            "River paddle",
            "ROUTE",
        )
        assert (usage.distance, usage.duration) == (12, 70)
        assert usage.event_date_range.start == datetime(2024, 3, 1, 9, tzinfo=UTC)

    async def test_route_on_a_journal_without_fitness_has_no_metrics(
        self, async_connection: AsyncConnection
    ) -> None:
        seeder = Seeder(async_connection)
        journal_id = await seeder.create_journal(title="Walk plan")
        route_id = await seeder.create_route(journal_id=journal_id)

        rows = await SqlRouteRepository(async_connection).find_usage_history(
            USER_ID, route_id
        )

        assert [(row.journal_id, row.distance, row.duration) for row in rows] == [
            (journal_id, None, None)
        ]

    async def test_another_users_route_has_no_usage(
        self, async_connection: AsyncConnection
    ) -> None:
        seeder = Seeder(async_connection)
        journal_id = await seeder.create_journal(user_id=OTHER_USER_ID)
        route_id = await seeder.create_route(journal_id=journal_id)

        repo = SqlRouteRepository(async_connection)

        assert await repo.find_usage_history(USER_ID, route_id) == []
        assert await repo.find_usage_history(USER_ID, uuid4()) == []
