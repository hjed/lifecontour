"""Unit tests for the outdoor dashboard MCP summary line.

``build_dashboard_summary`` is the one piece of pure logic Phase 3 adds on
top of the dashboard services: it counts across the four sections (summing
the 30-day totals and counting unique templates across the type groups) and
pluralises the summary sentence.
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
            activity_totals_last_30_days={},
            templates_done={},
        )

        assert summary == (
            "Dashboard: 0 upcoming activities, 0 gear items checked out, "
            "0 outdoor activities in the last 30 days, 0 unique templates done."
        )

    def test_counts_sum_totals_and_unique_templates_across_groups(self) -> None:
        summary = build_dashboard_summary(
            upcoming_activities=[_upcoming(1), _upcoming(2)],
            checked_out_gear=[_gear(3)],
            activity_totals_last_30_days={"canyoning": 2, "bushwalking": 1},
            templates_done={
                "canyoning": [_template("Empress Falls", 2), _template("Claustral")],
                "climbing": [_template("Sweet Dreams")],
            },
        )

        assert summary == (
            "Dashboard: 2 upcoming activities, 1 gear item checked out, "
            "3 outdoor activities in the last 30 days, 3 unique templates done."
        )

    def test_singular_forms(self) -> None:
        summary = build_dashboard_summary(
            upcoming_activities=[_upcoming(1)],
            checked_out_gear=[_gear(2)],
            activity_totals_last_30_days={"canyoning": 1},
            templates_done={"canyoning": [_template("Empress Falls")]},
        )

        assert summary == (
            "Dashboard: 1 upcoming activity, 1 gear item checked out, "
            "1 outdoor activity in the last 30 days, 1 unique template done."
        )
