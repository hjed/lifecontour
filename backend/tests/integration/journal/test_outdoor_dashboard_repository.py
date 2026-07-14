"""Integration tests for the outdoor dashboard projections.

Exercises the real ``SqlOutdoorDashboardRepository`` and the
``OutdoorDashboardService`` against Docker PostgreSQL. Each test seeds its own
journals via the repositories (anchored on ``datetime.now(UTC)`` captured once
per test), so outcomes are deterministic.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.outdoor_dashboard_repository import (
    SqlOutdoorDashboardRepository,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
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


def _upcoming_window(anchor_day: datetime) -> tuple[datetime, datetime]:
    """The service's upcoming window: [anchor 00:00, anchor+30d end-of-day]."""
    start_day = anchor_day.date()
    return (
        datetime.combine(start_day, time.min, UTC),
        datetime.combine(start_day + timedelta(days=30), time.max, UTC),
    )


def _totals_window(anchor_day: datetime) -> tuple[datetime, datetime]:
    """The service's totals window: [anchor-365d 00:00, anchor end-of-day]."""
    end_day = anchor_day.date()
    return (
        datetime.combine(end_day - timedelta(days=365), time.min, UTC),
        datetime.combine(end_day, time.max, UTC),
    )


@pytest_asyncio.fixture
async def dashboard_repository(
    async_connection: AsyncConnection,
) -> SqlOutdoorDashboardRepository:
    return SqlOutdoorDashboardRepository(async_connection)


@pytest_asyncio.fixture
async def user_settings_repository(
    async_connection: AsyncConnection,
) -> SqlUserSettingsRepository:
    return SqlUserSettingsRepository(async_connection)


@pytest_asyncio.fixture
async def service(
    dashboard_repository: SqlOutdoorDashboardRepository,
    user_settings_repository: SqlUserSettingsRepository,
) -> OutdoorDashboardService:
    return OutdoorDashboardService(
        dashboard_repo=dashboard_repository,
        user_settings_repo=user_settings_repository,
    )


@pytest_asyncio.fixture
async def seeder(async_connection: AsyncConnection) -> Seeder:
    return Seeder(async_connection)


@pytest.mark.integration
class TestUpcomingJournals:
    async def test_upcoming_returns_future_outdoor_and_planning_journals(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        outdoor_id = await seeder.create_incomplete_canyoning_journal(
            title="Canyon trip", start=now + timedelta(days=3)
        )
        planning_id = await seeder.create_outdoor_planning_journal(
            title="Planning night", start=now + timedelta(days=5)
        )
        window_start, window_end = _upcoming_window(now)

        result = await dashboard_repository.list_upcoming_journals(
            USER_ID, window_start=window_start, window_end=window_end
        )

        by_id = {entry.journal_id: entry for entry in result}
        assert set(by_id) == {outdoor_id, planning_id}
        outdoor = by_id[outdoor_id]
        assert outdoor.title == "Canyon trip"
        assert not outdoor.is_planning
        assert {subtype.value for subtype in outdoor.subtypes} == {
            "canyoning",
            "bushwalking",
            "abseiling_trip",
        }
        planning = by_id[planning_id]
        assert planning.title == "Planning night"
        assert planning.is_planning
        assert planning.subtypes == []

    async def test_upcoming_window_bounds_inclusive(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        window_start, window_end = _upcoming_window(now)
        # Late on the final day of the window: included.
        final_day_id = await seeder.create_outdoor_journal(
            title="Final day",
            start=datetime.combine(now.date() + timedelta(days=30), time(23, 0), UTC),
        )
        # Final fractional second of the window's last day: still included.
        final_fraction_id = await seeder.create_outdoor_journal(
            title="Final fraction",
            start=datetime.combine(
                now.date() + timedelta(days=30), time(23, 59, 59, 500000), UTC
            ),
        )
        # Started yesterday but still running tomorrow: included (overlap).
        in_progress_id = await seeder.create_outdoor_journal(
            title="In progress",
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )
        # Beyond the window: excluded.
        await seeder.create_outdoor_journal(
            title="Too far", start=now + timedelta(days=32)
        )
        # Ended before the window: excluded.
        await seeder.create_outdoor_journal(
            title="Ended yesterday", start=now - timedelta(days=1, hours=2)
        )

        result = await dashboard_repository.list_upcoming_journals(
            USER_ID, window_start=window_start, window_end=window_end
        )

        assert {entry.journal_id for entry in result} == {
            final_day_id,
            final_fraction_id,
            in_progress_id,
        }

    async def test_upcoming_excludes_non_outdoor_journals(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        outdoor_id = await seeder.create_outdoor_journal(
            title="Paddle", start=now + timedelta(days=2)
        )
        await seeder.create_jogging_journal(title="Jog", start=now + timedelta(days=2))
        await seeder.create_journal(title="Note", start=now + timedelta(days=2))
        window_start, window_end = _upcoming_window(now)

        result = await dashboard_repository.list_upcoming_journals(
            USER_ID, window_start=window_start, window_end=window_end
        )

        assert [entry.journal_id for entry in result] == [outdoor_id]

    async def test_upcoming_excludes_other_users_journals(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        mine_id = await seeder.create_outdoor_journal(
            title="Mine", start=now + timedelta(days=2)
        )
        await seeder.create_outdoor_journal(
            title="Theirs", user_id=OTHER_USER_ID, start=now + timedelta(days=2)
        )
        window_start, window_end = _upcoming_window(now)

        result = await dashboard_repository.list_upcoming_journals(
            USER_ID, window_start=window_start, window_end=window_end
        )

        assert [entry.journal_id for entry in result] == [mine_id]


@pytest.mark.integration
class TestOutdoorTypeFacts:
    async def test_totals_rows_scoped_to_window_and_user(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        recent_id = await seeder.create_outdoor_journal(
            title="Recent", start=now - timedelta(days=10)
        )
        old_in_window_id = await seeder.create_outdoor_journal(
            title="Old", start=now - timedelta(days=100)
        )
        await seeder.create_outdoor_journal(
            title="Ancient", start=now - timedelta(days=400)
        )
        await seeder.create_outdoor_journal(
            title="Theirs", user_id=OTHER_USER_ID, start=now - timedelta(days=10)
        )
        window_start, window_end = _totals_window(now)

        result = await dashboard_repository.list_outdoor_type_facts(
            USER_ID, window_start=window_start, window_end=window_end
        )

        assert {entry.journal_id for entry in result} == {
            recent_id,
            old_in_window_id,
        }

    async def test_totals_excludes_jogging_and_planning_journals(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        outdoor_id = await seeder.create_outdoor_journal(
            title="Paddle", start=now - timedelta(days=5)
        )
        await seeder.create_jogging_journal(title="Jog", start=now - timedelta(days=5))
        await seeder.create_outdoor_planning_journal(
            title="Planning", start=now - timedelta(days=5)
        )
        window_start, window_end = _totals_window(now)

        result = await dashboard_repository.list_outdoor_type_facts(
            USER_ID, window_start=window_start, window_end=window_end
        )

        assert [entry.journal_id for entry in result] == [outdoor_id]

    async def test_totals_carries_subtype_flags_for_composite_journal(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        canyoning_id = await seeder.create_incomplete_canyoning_journal(
            title="Canyon", start=now - timedelta(days=5)
        )
        window_start, window_end = _totals_window(now)

        result = await dashboard_repository.list_outdoor_type_facts(
            USER_ID, window_start=window_start, window_end=window_end
        )

        assert len(result) == 1
        entry = result[0]
        assert entry.journal_id == canyoning_id
        assert {subtype.value for subtype in entry.subtypes} == {
            "canyoning",
            "bushwalking",
            "abseiling_trip",
        }


@pytest.mark.integration
class TestDashboardServiceEndToEnd:
    async def test_service_totals_and_upcoming_against_seeded_data(
        self,
        seeder: Seeder,
        service: OutdoorDashboardService,
    ) -> None:
        now = datetime.now(UTC)
        # Totals mix: one canyoning trip 10 days ago (both windows), one plain
        # outdoor journal 100 days ago (365-day window only).
        await seeder.create_incomplete_canyoning_journal(
            title="Canyon", start=now - timedelta(days=10)
        )
        await seeder.create_outdoor_journal(
            title="Old walk", start=now - timedelta(days=100)
        )
        # Eleven future journals: the upcoming list caps at ten, soonest first.
        future_ids = [
            await seeder.create_outdoor_journal(
                title=f"Trip {day}", start=now + timedelta(days=day)
            )
            for day in range(1, 12)
        ]

        totals = await service.activity_totals(USER_ID)
        upcoming = await service.list_upcoming_activities(USER_ID)

        assert totals.last_30_days == {"canyoning": 1}
        assert totals.last_365_days == {"canyoning": 1, "outdoor_activity": 1}
        assert len(upcoming) == 10
        assert [entry.journal_id for entry in upcoming] == future_ids[:10]

    async def test_windows_follow_stored_user_timezone(
        self,
        seeder: Seeder,
        service: OutdoorDashboardService,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """Window boundaries sit at the user's local midnight, not UTC's.

        With ``Australia/Sydney`` (UTC+10) and an explicit anchor, the
        upcoming window opens at 2026-06-30T14:00Z (Sydney midnight), so a
        journal at 2026-06-30T20:00Z — before UTC's July 1 — is included,
        while the totals window closes at 2026-07-01T13:59:59Z, so a journal
        at 2026-07-01T20:00Z — still July 1 UTC — is excluded.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        anchor = date(2026, 7, 1)
        upcoming_included = await seeder.create_outdoor_journal(
            title="July 1st 6am Sydney",
            start=datetime(2026, 6, 30, 20, 0, tzinfo=UTC),
        )
        totals_included = await seeder.create_outdoor_journal(
            title="July 1st 8pm Sydney",
            start=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
        )
        # July 2nd 06:00 in Sydney: beyond the totals window, inside upcoming.
        totals_excluded = await seeder.create_outdoor_journal(
            title="July 2nd 6am Sydney",
            start=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
        )

        upcoming = await service.list_upcoming_activities(USER_ID, anchor=anchor)
        totals = await service.activity_totals(USER_ID, anchor=anchor)

        assert [entry.journal_id for entry in upcoming] == [
            upcoming_included,
            totals_included,
            totals_excluded,
        ]
        assert totals.last_365_days == {"outdoor_activity": 2}
