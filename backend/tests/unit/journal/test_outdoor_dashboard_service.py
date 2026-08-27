"""Unit tests for OutdoorDashboardService.

Pins the dashboard read rules: the upcoming widget's 30-day window, cap of 10
and soonest-first ordering, the totals widget's rolling 30/365-day window
bucketing grouped by effective journal type, the user-timezone window
anchoring (boundaries at the user's local midnight, not UTC's), the
checked-out-gear filtering, and the templates-done grouping.
"""

import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import (
    EventDateRange,
    GearCheckoutFacts,
    OutdoorActivitySubtype,
    OutdoorActivityTypeFacts,
    TemplateDone,
    TemplateReferenceFacts,
    UpcomingOutdoorActivity,
)

from app.core.journal.services.journal_date_resolver import (
    JournalDateResolver,
)
from app.core.journal.services.outdoor_dashboard_service import (
    UPCOMING_CAP,
    OutdoorDashboardService,
)

USER_ID = "test-user-123"
ANCHOR = datetime.date(2026, 7, 1)
NOW = datetime.datetime(2026, 7, 14, 12, 0, tzinfo=datetime.UTC)


def _range(
    start: datetime.datetime, end: datetime.datetime | None = None
) -> EventDateRange:
    return EventDateRange(start=start, end=end or start)


def make_upcoming(
    journal_id: int,
    start: datetime.datetime,
    *,
    end: datetime.datetime | None = None,
) -> UpcomingOutdoorActivity:
    return UpcomingOutdoorActivity(
        journal_id=journal_id,
        title=f"Journal {journal_id}",
        event_date_range=_range(start, end),
        subtypes=[OutdoorActivitySubtype.KAYAKING],
    )


def make_type_facts(
    journal_id: int,
    start: datetime.datetime,
    *,
    end: datetime.datetime | None = None,
    subtypes: list[OutdoorActivitySubtype] | None = None,
) -> OutdoorActivityTypeFacts:
    return OutdoorActivityTypeFacts(
        journal_id=journal_id,
        event_date_range=_range(start, end),
        subtypes=(
            subtypes if subtypes is not None else [OutdoorActivitySubtype.KAYAKING]
        ),
    )


def make_template_reference(
    journal_id: int,
    start: datetime.datetime,
    *,
    end: datetime.datetime | None = None,
    template_id: str = "22222222-2222-2222-2222-222222222222",
    template_name: str = "Empress Falls",
    template_type: str = "canyoning",
) -> TemplateReferenceFacts:
    return TemplateReferenceFacts(
        journal_id=journal_id,
        template_id=template_id,
        template_name=template_name,
        template_type=template_type,
        event_date_range=_range(start, end),
    )


def make_checkout_facts(
    *,
    journal_id: int = 1,
    gear_item_id: str = "11111111-1111-1111-1111-111111111111",
    gear_name: str = "Rope",
    checkout_date: datetime.datetime | None = None,
    checkin_date: datetime.datetime | None = None,
    snipeit_checked_in: bool = False,
) -> GearCheckoutFacts:
    return GearCheckoutFacts(
        journal_id=journal_id,
        gear_item_id=gear_item_id,
        gear_name=gear_name,
        checkout_date=checkout_date or NOW - datetime.timedelta(days=1),
        checkin_date=checkin_date or NOW + datetime.timedelta(days=1),
        snipeit_checked_in=snipeit_checked_in,
    )


@pytest.fixture
def mock_dashboard_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_upcoming_journals.return_value = []
    repo.list_outdoor_type_facts.return_value = []
    repo.list_gear_checkout_facts.return_value = []
    repo.list_template_references.return_value = []
    return repo


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def service(
    mock_dashboard_repo: AsyncMock, mock_settings_repo: AsyncMock
) -> OutdoorDashboardService:
    """The service over the real date resolver and a stubbed settings row.

    Real rather than mocked so the timezone and window rules under test are the
    ones that run in production.
    """
    return OutdoorDashboardService(
        dashboard_repo=mock_dashboard_repo,
        date_resolver=JournalDateResolver(user_settings_repo=mock_settings_repo),
    )


class TestListUpcomingActivities:
    @pytest.mark.asyncio
    async def test_caps_results_at_ten(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        mock_dashboard_repo.list_upcoming_journals.return_value = [
            make_upcoming(i, datetime.datetime(2026, 7, 1 + i, tzinfo=datetime.UTC))
            for i in range(1, 13)
        ]

        result = await service.list_upcoming_activities(USER_ID, anchor=ANCHOR)

        assert len(result) == UPCOMING_CAP == 10
        # The cap keeps the most imminent entries.
        assert [entry.journal_id for entry in result] == list(range(1, 11))

    @pytest.mark.asyncio
    async def test_orders_soonest_first_with_id_tiebreak(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        same_day = datetime.datetime(2026, 7, 10, tzinfo=datetime.UTC)
        mock_dashboard_repo.list_upcoming_journals.return_value = [
            make_upcoming(30, datetime.datetime(2026, 7, 20, tzinfo=datetime.UTC)),
            make_upcoming(20, same_day),
            make_upcoming(10, same_day),
            make_upcoming(40, datetime.datetime(2026, 7, 2, tzinfo=datetime.UTC)),
        ]

        result = await service.list_upcoming_activities(USER_ID, anchor=ANCHOR)

        assert [entry.journal_id for entry in result] == [40, 10, 20, 30]

    @pytest.mark.asyncio
    async def test_computes_thirty_day_window_from_anchor(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        await service.list_upcoming_activities(USER_ID, anchor=ANCHOR)

        mock_dashboard_repo.list_upcoming_journals.assert_awaited_once_with(
            USER_ID,
            window_start=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
            window_end=datetime.datetime(
                2026, 7, 31, 23, 59, 59, 999999, tzinfo=datetime.UTC
            ),
        )

    @pytest.mark.asyncio
    async def test_scopes_repo_call_to_user(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        await service.list_upcoming_activities("other-user", anchor=ANCHOR)

        call = mock_dashboard_repo.list_upcoming_journals.await_args
        assert call.args[0] == "other-user"

    @pytest.mark.asyncio
    async def test_window_boundaries_use_user_timezone(
        self,
        service: OutdoorDashboardService,
        mock_dashboard_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
    ) -> None:
        """Windows run midnight→end-of-day in the user's timezone, not UTC's."""
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"
        sydney = ZoneInfo("Australia/Sydney")

        await service.list_upcoming_activities(USER_ID, anchor=ANCHOR)

        mock_settings_repo.get_timezone.assert_awaited_once_with(USER_ID)
        mock_dashboard_repo.list_upcoming_journals.assert_awaited_once_with(
            USER_ID,
            window_start=datetime.datetime(2026, 7, 1, tzinfo=sydney),
            window_end=datetime.datetime(
                2026, 7, 31, 23, 59, 59, 999999, tzinfo=sydney
            ),
        )

    @pytest.mark.asyncio
    async def test_invalid_timezone_falls_back_to_utc(
        self,
        service: OutdoorDashboardService,
        mock_dashboard_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
    ) -> None:
        mock_settings_repo.get_timezone.return_value = "Not/AZone"

        await service.list_upcoming_activities(USER_ID, anchor=ANCHOR)

        mock_dashboard_repo.list_upcoming_journals.assert_awaited_once_with(
            USER_ID,
            window_start=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
            window_end=datetime.datetime(
                2026, 7, 31, 23, 59, 59, 999999, tzinfo=datetime.UTC
            ),
        )


class TestActivityTotals:
    @pytest.mark.asyncio
    async def test_fetches_single_365_day_window_from_anchor(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        await service.activity_totals(USER_ID, anchor=ANCHOR)

        mock_dashboard_repo.list_outdoor_type_facts.assert_awaited_once_with(
            USER_ID,
            window_start=datetime.datetime(2025, 7, 1, tzinfo=datetime.UTC),
            window_end=datetime.datetime(
                2026, 7, 1, 23, 59, 59, 999999, tzinfo=datetime.UTC
            ),
        )

    @pytest.mark.asyncio
    async def test_groups_counts_per_window(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        mock_dashboard_repo.list_outdoor_type_facts.return_value = [
            # 10 days before the anchor: inside both windows.
            make_type_facts(1, datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC)),
            # 100 days before the anchor: only inside the 365-day window.
            make_type_facts(2, datetime.datetime(2026, 3, 23, tzinfo=datetime.UTC)),
        ]

        totals = await service.activity_totals(USER_ID, anchor=ANCHOR)

        assert totals.last_30_days == {"kayaking": 1}
        assert totals.last_365_days == {"kayaking": 2}

    @pytest.mark.asyncio
    async def test_window_bucketing_uses_overlap_bounds(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        # Started before the 30-day boundary (2026-06-01) but ended inside it.
        mock_dashboard_repo.list_outdoor_type_facts.return_value = [
            make_type_facts(
                1,
                datetime.datetime(2026, 5, 25, tzinfo=datetime.UTC),
                end=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
            ),
        ]

        totals = await service.activity_totals(USER_ID, anchor=ANCHOR)

        assert totals.last_30_days == {"kayaking": 1}
        assert totals.last_365_days == {"kayaking": 1}

    @pytest.mark.asyncio
    async def test_reduces_dependency_subtypes_to_primary_type(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        mock_dashboard_repo.list_outdoor_type_facts.return_value = [
            make_type_facts(
                1,
                datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC),
                subtypes=[
                    OutdoorActivitySubtype.CANYONING,
                    OutdoorActivitySubtype.BUSHWALKING,
                    OutdoorActivitySubtype.ABSEILING_TRIP,
                ],
            ),
        ]

        totals = await service.activity_totals(USER_ID, anchor=ANCHOR)

        assert totals.last_30_days == {"canyoning": 1}
        assert totals.last_365_days == {"canyoning": 1}

    @pytest.mark.asyncio
    async def test_subtypeless_outdoor_journal_counts_as_outdoor_activity(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        mock_dashboard_repo.list_outdoor_type_facts.return_value = [
            make_type_facts(
                1, datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC), subtypes=[]
            ),
        ]

        totals = await service.activity_totals(USER_ID, anchor=ANCHOR)

        assert totals.last_30_days == {"outdoor_activity": 1}
        assert totals.last_365_days == {"outdoor_activity": 1}

    @pytest.mark.asyncio
    async def test_both_windows_returned_together_with_empty_dicts_when_no_rows(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        totals = await service.activity_totals(USER_ID, anchor=ANCHOR)

        assert totals.last_30_days == {}
        assert totals.last_365_days == {}
        assert totals.total_last_30_days == 0
        assert totals.total_last_365_days == 0

    @pytest.mark.asyncio
    async def test_totals_count_journals_once_per_window(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        mock_dashboard_repo.list_outdoor_type_facts.return_value = [
            # 10 days before the anchor: inside both windows.
            make_type_facts(1, datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC)),
            # 100 days before the anchor: only inside the 365-day window.
            make_type_facts(2, datetime.datetime(2026, 3, 23, tzinfo=datetime.UTC)),
        ]

        totals = await service.activity_totals(USER_ID, anchor=ANCHOR)

        assert totals.total_last_30_days == 1
        assert totals.total_last_365_days == 2

    @pytest.mark.asyncio
    async def test_a_multi_type_journal_counts_once_in_the_totals(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        # Two genuinely independent subtypes: the journal contributes to two
        # per-type buckets but is a single logged activity.
        mock_dashboard_repo.list_outdoor_type_facts.return_value = [
            make_type_facts(
                1,
                datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC),
                subtypes=[
                    OutdoorActivitySubtype.KAYAKING,
                    OutdoorActivitySubtype.CLIMBING,
                ],
            ),
        ]

        totals = await service.activity_totals(USER_ID, anchor=ANCHOR)

        assert totals.last_30_days == {"climbing": 1, "kayaking": 1}
        assert totals.total_last_30_days == 1
        assert totals.total_last_365_days == 1

    @pytest.mark.asyncio
    async def test_totals_window_uses_user_timezone(
        self,
        service: OutdoorDashboardService,
        mock_dashboard_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
    ) -> None:
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"
        sydney = ZoneInfo("Australia/Sydney")

        await service.activity_totals(USER_ID, anchor=ANCHOR)

        mock_dashboard_repo.list_outdoor_type_facts.assert_awaited_once_with(
            USER_ID,
            window_start=datetime.datetime(2025, 7, 1, tzinfo=sydney),
            window_end=datetime.datetime(2026, 7, 1, 23, 59, 59, 999999, tzinfo=sydney),
        )


class TestListCheckedOutGear:
    @pytest.mark.asyncio
    async def test_passes_now_as_ending_after_bound(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        await service.list_checked_out_gear(USER_ID, now=NOW)

        mock_dashboard_repo.list_gear_checkout_facts.assert_awaited_once_with(
            USER_ID, ending_after=NOW
        )

    @pytest.mark.asyncio
    async def test_defaults_now_to_current_utc_time(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        before = datetime.datetime.now(datetime.UTC)
        await service.list_checked_out_gear(USER_ID)
        after = datetime.datetime.now(datetime.UTC)

        call = mock_dashboard_repo.list_gear_checkout_facts.await_args
        assert before <= call.kwargs["ending_after"] <= after

    @pytest.mark.asyncio
    async def test_filters_and_maps_open_checkouts(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        mock_dashboard_repo.list_gear_checkout_facts.return_value = [
            make_checkout_facts(journal_id=1, gear_name="Rope"),
            # Not yet checked out: window starts tomorrow.
            make_checkout_facts(
                journal_id=2,
                gear_item_id="33333333-3333-3333-3333-333333333333",
                checkout_date=NOW + datetime.timedelta(days=1),
                checkin_date=NOW + datetime.timedelta(days=2),
            ),
            # Already returned in Snipe-IT.
            make_checkout_facts(
                journal_id=3,
                gear_item_id="44444444-4444-4444-4444-444444444444",
                snipeit_checked_in=True,
            ),
        ]

        result = await service.list_checked_out_gear(USER_ID, now=NOW)

        assert [item.journal_id for item in result] == [1]
        assert result[0].name == "Rope"
        assert result[0].checked_out_since == NOW - datetime.timedelta(days=1)

    @pytest.mark.asyncio
    async def test_no_open_checkouts_yield_empty_list(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        assert await service.list_checked_out_gear(USER_ID, now=NOW) == []


class TestTemplatesDone:
    @pytest.mark.asyncio
    async def test_scopes_repo_call_to_user(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        await service.templates_done("other-user", anchor=ANCHOR)

        mock_dashboard_repo.list_template_references.assert_awaited_once_with(
            "other-user"
        )

    @pytest.mark.asyncio
    async def test_groups_references_by_template_type_with_counts(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        canyon_template = "22222222-2222-2222-2222-222222222222"
        climb_template = "55555555-5555-5555-5555-555555555555"
        done_on = datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC)
        mock_dashboard_repo.list_template_references.return_value = [
            make_template_reference(1, done_on, template_id=canyon_template),
            make_template_reference(2, done_on, template_id=canyon_template),
            make_template_reference(
                3,
                done_on,
                template_id=climb_template,
                template_name="Sweet Dreams",
                template_type="climbing",
            ),
        ]

        result = await service.templates_done(USER_ID, anchor=ANCHOR)

        assert result.by_type == {
            "canyoning": [
                TemplateDone(
                    template_id=canyon_template,
                    name="Empress Falls",
                    template_type="canyoning",
                    done_count=2,
                )
            ],
            "climbing": [
                TemplateDone(
                    template_id=climb_template,
                    name="Sweet Dreams",
                    template_type="climbing",
                    done_count=1,
                )
            ],
        }

    @pytest.mark.asyncio
    async def test_recent_count_is_unique_templates_in_the_last_thirty_days(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        canyon_template = "22222222-2222-2222-2222-222222222222"
        climb_template = "55555555-5555-5555-5555-555555555555"
        mock_dashboard_repo.list_template_references.return_value = [
            # Same canyon done twice inside the window: one unique template.
            make_template_reference(
                1,
                datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC),
                template_id=canyon_template,
            ),
            make_template_reference(
                2,
                datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
                template_id=canyon_template,
            ),
            # A different template, also inside the window.
            make_template_reference(
                3,
                datetime.datetime(2026, 6, 28, tzinfo=datetime.UTC),
                template_id=climb_template,
                template_name="Sweet Dreams",
                template_type="climbing",
            ),
        ]

        result = await service.templates_done(USER_ID, anchor=ANCHOR)

        assert result.recent_unique_count == 2

    @pytest.mark.asyncio
    async def test_recent_count_excludes_templates_done_before_the_window(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        mock_dashboard_repo.list_template_references.return_value = [
            # 100 days before the anchor: grouped, but not "recent".
            make_template_reference(
                1, datetime.datetime(2026, 3, 23, tzinfo=datetime.UTC)
            ),
        ]

        result = await service.templates_done(USER_ID, anchor=ANCHOR)

        assert result.recent_unique_count == 0
        assert set(result.by_type) == {"canyoning"}

    @pytest.mark.asyncio
    async def test_recent_window_uses_user_timezone(
        self,
        service: OutdoorDashboardService,
        mock_dashboard_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
    ) -> None:
        # Sydney is UTC+10, so its 30-day window opens 10 hours earlier than
        # UTC's. A trip at 2026-05-31T20:00Z is 2026-06-01T06:00 in Sydney —
        # inside the Sydney window, outside the UTC one.
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"
        mock_dashboard_repo.list_template_references.return_value = [
            make_template_reference(
                1, datetime.datetime(2026, 5, 31, 20, 0, tzinfo=datetime.UTC)
            ),
        ]

        result = await service.templates_done(USER_ID, anchor=ANCHOR)

        assert result.recent_unique_count == 1

    @pytest.mark.asyncio
    async def test_no_references_yield_empty_summary(
        self, service: OutdoorDashboardService, mock_dashboard_repo: AsyncMock
    ) -> None:
        result = await service.templates_done(USER_ID, anchor=ANCHOR)

        assert result.by_type == {}
        assert result.recent_unique_count == 0
