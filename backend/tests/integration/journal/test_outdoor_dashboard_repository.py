"""Integration tests for the outdoor dashboard projections.

Exercises the real ``SqlOutdoorDashboardRepository`` and the
``OutdoorDashboardService`` against Docker PostgreSQL. Each test seeds its own
journals via the repositories (anchored on ``datetime.now(UTC)`` captured once
per test), so outcomes are deterministic. Covers the upcoming/totals windows,
the checked-out-gear resolution (buffer dates over event range, the
``snipeit_checkin`` exclusion) and the templates-done aggregation.
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


@pytest.mark.integration
class TestGearCheckoutFacts:
    async def test_open_checkout_resolves_dates_from_event_range(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        gear_id = await seeder.create_gear_item(name="Rope")
        journal_id = await seeder.create_gear_usage_journal(
            gear_id, start=now - timedelta(days=1), end=now + timedelta(days=1)
        )

        result = await dashboard_repository.list_gear_checkout_facts(
            USER_ID, ending_after=now
        )

        assert len(result) == 1
        facts = result[0]
        assert facts.journal_id == journal_id
        assert facts.gear_item_id == gear_id
        assert facts.gear_name == "Rope"
        assert facts.checkout_date == now - timedelta(days=1)
        assert facts.checkin_date == now + timedelta(days=1)
        assert not facts.snipeit_checked_in

    async def test_buffer_dates_take_precedence_over_event_range(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        gear_id = await seeder.create_gear_item(name="Harness")
        await seeder.create_gear_usage_journal(
            gear_id,
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
            # Packed the day before, returning the day after the trip.
            checkout_date=now - timedelta(days=2),
            checkin_date=now + timedelta(days=2),
        )

        result = await dashboard_repository.list_gear_checkout_facts(
            USER_ID, ending_after=now
        )

        assert len(result) == 1
        assert result[0].checkout_date == now - timedelta(days=2)
        assert result[0].checkin_date == now + timedelta(days=2)

    async def test_ended_checkouts_are_excluded(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        gear_id = await seeder.create_gear_item(name="Rope")
        open_id = await seeder.create_gear_usage_journal(
            gear_id,
            title="Open",
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )
        # Usage window fully in the past: the gear has been returned.
        await seeder.create_gear_usage_journal(
            gear_id,
            title="Closed",
            start=now - timedelta(days=10),
            end=now - timedelta(days=8),
        )

        result = await dashboard_repository.list_gear_checkout_facts(
            USER_ID, ending_after=now
        )

        assert [facts.journal_id for facts in result] == [open_id]

    async def test_snipeit_checkin_row_flags_the_checkout(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        gear_id = await seeder.create_gear_item(name="Rope")
        returned_id = await seeder.create_gear_usage_journal(
            gear_id,
            title="Returned early",
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )
        await seeder.insert_snipeit_checkin(returned_id)

        result = await dashboard_repository.list_gear_checkout_facts(
            USER_ID, ending_after=now
        )

        assert len(result) == 1
        assert result[0].snipeit_checked_in

    async def test_failed_snipeit_checkin_does_not_flag_the_checkout(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        gear_id = await seeder.create_gear_item(name="Rope")
        journal_id = await seeder.create_gear_usage_journal(
            gear_id, start=now - timedelta(days=1), end=now + timedelta(days=1)
        )
        await seeder.insert_snipeit_checkin(journal_id, sync_status="failed")

        result = await dashboard_repository.list_gear_checkout_facts(
            USER_ID, ending_after=now
        )

        assert len(result) == 1
        assert not result[0].snipeit_checked_in

    async def test_excludes_other_users_checkouts(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        mine_gear = await seeder.create_gear_item(name="Mine")
        theirs_gear = await seeder.create_gear_item(
            name="Theirs", user_id=OTHER_USER_ID
        )
        mine_id = await seeder.create_gear_usage_journal(
            mine_gear, start=now - timedelta(days=1), end=now + timedelta(days=1)
        )
        await seeder.create_gear_usage_journal(
            theirs_gear,
            user_id=OTHER_USER_ID,
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )

        result = await dashboard_repository.list_gear_checkout_facts(
            USER_ID, ending_after=now
        )

        assert [facts.journal_id for facts in result] == [mine_id]

    async def test_service_excludes_future_and_returned_checkouts(
        self,
        seeder: Seeder,
        service: OutdoorDashboardService,
    ) -> None:
        now = datetime.now(UTC)
        rope = await seeder.create_gear_item(name="Rope")
        harness = await seeder.create_gear_item(name="Harness")
        helmet = await seeder.create_gear_item(name="Helmet")
        open_id = await seeder.create_gear_usage_journal(
            rope,
            title="Out now",
            start=now - timedelta(days=2),
            end=now + timedelta(days=1),
        )
        # Next week's trip: not yet checked out.
        await seeder.create_gear_usage_journal(
            harness,
            title="Next week",
            start=now + timedelta(days=7),
            end=now + timedelta(days=9),
        )
        # Open window but already returned in Snipe-IT.
        returned_id = await seeder.create_gear_usage_journal(
            helmet,
            title="Returned early",
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )
        await seeder.insert_snipeit_checkin(returned_id)

        result = await service.list_checked_out_gear(USER_ID)

        assert [item.journal_id for item in result] == [open_id]
        assert result[0].name == "Rope"
        assert result[0].gear_item_id == rope
        assert result[0].checked_out_since == now - timedelta(days=2)

    async def test_service_returns_empty_list_when_nothing_checked_out(
        self,
        service: OutdoorDashboardService,
    ) -> None:
        assert await service.list_checked_out_gear(USER_ID) == []


@pytest.mark.integration
class TestTemplateReferences:
    async def test_references_join_templates_scoped_to_user(
        self,
        seeder: Seeder,
        dashboard_repository: SqlOutdoorDashboardRepository,
    ) -> None:
        now = datetime.now(UTC)
        template_id = await seeder.create_template(
            name="Empress Falls", template_type="canyoning"
        )
        journal_id = await seeder.create_abseiling_journal(
            start=now - timedelta(days=5), template_id=template_id
        )
        # No template reference: not a "done" template row.
        await seeder.create_abseiling_journal(start=now - timedelta(days=4))
        # Another user's journal referencing their own template.
        other_template = await seeder.create_template(
            name="Their canyon", user_id=OTHER_USER_ID
        )
        await seeder.create_abseiling_journal(
            user_id=OTHER_USER_ID,
            start=now - timedelta(days=3),
            template_id=other_template,
        )

        result = await dashboard_repository.list_template_references(USER_ID)

        assert len(result) == 1
        reference = result[0]
        assert reference.journal_id == journal_id
        assert reference.template_id == template_id
        assert reference.template_name == "Empress Falls"
        assert reference.template_type == "canyoning"

    async def test_service_groups_and_counts_templates_done(
        self,
        seeder: Seeder,
        service: OutdoorDashboardService,
    ) -> None:
        now = datetime.now(UTC)
        canyon = await seeder.create_template(
            name="Empress Falls", template_type="canyoning"
        )
        climb = await seeder.create_template(
            name="Sweet Dreams", template_type="climbing"
        )
        await seeder.create_abseiling_journal(
            title="First run", start=now - timedelta(days=30), template_id=canyon
        )
        await seeder.create_abseiling_journal(
            title="Second run", start=now - timedelta(days=10), template_id=canyon
        )
        await seeder.create_abseiling_journal(
            title="Climb", start=now - timedelta(days=5), template_id=climb
        )

        result = await service.templates_done(USER_ID)

        assert set(result) == {"canyoning", "climbing"}
        assert [(entry.name, entry.done_count) for entry in result["canyoning"]] == [
            ("Empress Falls", 2)
        ]
        assert [(entry.name, entry.done_count) for entry in result["climbing"]] == [
            ("Sweet Dreams", 1)
        ]

    async def test_service_returns_empty_mapping_without_references(
        self,
        service: OutdoorDashboardService,
    ) -> None:
        assert await service.templates_done(USER_ID) == {}
