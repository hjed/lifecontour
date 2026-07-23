"""Unit tests for the outdoor dashboard MCP summary line.

``build_dashboard_summary`` is the one piece of pure logic the MCP dashboard
tool adds on top of the dashboard services: it counts across the four sections
and pluralises the summary sentence.

The activity and recent-template counts are taken from the service's
distinct-journal / distinct-template numbers rather than summed out of the
per-type mappings, because a journal with two independent subtypes appears in
two type buckets while being one logged activity.
"""

from datetime import UTC, datetime

from app.mcp.domains.journals.schemas import (
    CheckedOutGearMCPEntry,
    EventDateRangeSchema,
    TemplateDoneMCPEntry,
    UpcomingOutdoorActivityMCPEntry,
    build_dashboard_summary,
)


def _upcoming(journal_id: int) -> UpcomingOutdoorActivityMCPEntry:
    return UpcomingOutdoorActivityMCPEntry(
        journal_id=journal_id,
        title=f"Trip {journal_id}",
        event_date_range=EventDateRangeSchema(
            start=datetime(2026, 7, 20, 9, tzinfo=UTC),
            end=datetime(2026, 7, 20, 17, tzinfo=UTC),
        ),
        subtypes=["canyoning"],
        is_planning=False,
    )


def _gear(journal_id: int) -> CheckedOutGearMCPEntry:
    return CheckedOutGearMCPEntry(
        gear_item_id=f"gear-{journal_id}",
        name=f"Gear {journal_id}",
        checked_out_since=datetime(2026, 7, 10, 9, tzinfo=UTC),
        journal_id=journal_id,
    )


def _template(name: str, done_count: int = 1) -> TemplateDoneMCPEntry:
    return TemplateDoneMCPEntry(
        template_id=f"template-{name}", name=name, done_count=done_count
    )


class TestBuildDashboardSummary:
    def test_empty_dashboard(self) -> None:
        summary = build_dashboard_summary(
            upcoming_activities=[],
            checked_out_gear=[],
            total_last_30_days=0,
            templates_done={},
            templates_done_last_30_days=0,
        )

        assert summary == (
            "Dashboard: 0 upcoming activities, 0 gear items checked out, "
            "0 outdoor activities in the last 30 days, 0 unique templates done "
            "(0 in the last 30 days)."
        )

    def test_counts_activities_and_unique_templates_across_groups(self) -> None:
        summary = build_dashboard_summary(
            upcoming_activities=[_upcoming(1), _upcoming(2)],
            checked_out_gear=[_gear(3)],
            total_last_30_days=3,
            templates_done={
                "canyoning": [_template("Empress Falls", 2), _template("Claustral")],
                "climbing": [_template("Sweet Dreams")],
            },
            templates_done_last_30_days=2,
        )

        assert summary == (
            "Dashboard: 2 upcoming activities, 1 gear item checked out, "
            "3 outdoor activities in the last 30 days, 3 unique templates done "
            "(2 in the last 30 days)."
        )

    def test_activity_count_is_not_the_sum_of_the_per_type_buckets(self) -> None:
        # One journal recording two independent subtypes: two type buckets,
        # one logged activity. The caller passes the distinct count.
        summary = build_dashboard_summary(
            upcoming_activities=[],
            checked_out_gear=[],
            total_last_30_days=1,
            templates_done={},
            templates_done_last_30_days=0,
        )

        assert "1 outdoor activity in the last 30 days" in summary

    def test_singular_forms(self) -> None:
        summary = build_dashboard_summary(
            upcoming_activities=[_upcoming(1)],
            checked_out_gear=[_gear(2)],
            total_last_30_days=1,
            templates_done={"canyoning": [_template("Empress Falls")]},
            templates_done_last_30_days=1,
        )

        assert summary == (
            "Dashboard: 1 upcoming activity, 1 gear item checked out, "
            "1 outdoor activity in the last 30 days, 1 unique template done "
            "(1 in the last 30 days)."
        )
