"""Integration tests for the outdoor dashboard REST endpoint.

Exercises ``GET /api/journals/outdoor-dashboard`` end-to-end via the
``authenticated_client``. Each test seeds its own journals through the real
repositories (savepoint-isolated, anchored on ``datetime.now(UTC)``), so
outcomes are deterministic. The endpoint aggregates the four dashboard
sections built in ITER16-003 Phases 1-2: upcoming activities, checked-out
gear, activity totals and templates done.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.journal.outdoor_activity_seeding import (
    OTHER_USER_ID,
    USER_ID,
    Seeder,
)

pytestmark = pytest.mark.asyncio

URL = "/api/journals/outdoor-dashboard"


@pytest_asyncio.fixture
async def seeder(async_connection: AsyncConnection) -> Seeder:
    return Seeder(async_connection)


async def test_empty_dashboard_returns_singleton_resource_with_empty_sections(
    authenticated_client,
) -> None:
    response = await authenticated_client.get(URL)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["type"] == "outdoor-dashboards"
    assert data["id"] == USER_ID
    attributes = data["attributes"]
    assert attributes["upcoming_activities"] == []
    assert attributes["checked_out_gear"] == []
    assert attributes["activity_totals"] == {
        "last_30_days": {},
        "last_365_days": {},
        "total_last_30_days": 0,
        "total_last_365_days": 0,
    }
    assert attributes["templates_done"] == {}
    assert attributes["templates_done_last_30_days"] == 0


async def test_upcoming_lists_outdoor_and_planning_soonest_first(
    authenticated_client,
    seeder: Seeder,
) -> None:
    now = datetime.now(UTC)
    outdoor_id = await seeder.create_incomplete_canyoning_journal(
        title="Canyon trip", start=now + timedelta(days=3)
    )
    planning_id = await seeder.create_outdoor_planning_journal(
        title="Planning night", start=now + timedelta(days=5)
    )
    # Not outdoor: excluded even though it falls inside the window.
    await seeder.create_jogging_journal(title="Jog", start=now + timedelta(days=2))
    # Another user's journal: never visible.
    await seeder.create_outdoor_journal(
        title="Theirs", user_id=OTHER_USER_ID, start=now + timedelta(days=4)
    )
    # Beyond the 30-day window: excluded.
    await seeder.create_outdoor_journal(title="Too far", start=now + timedelta(days=40))

    response = await authenticated_client.get(URL)

    assert response.status_code == 200
    upcoming = response.json()["data"]["attributes"]["upcoming_activities"]
    assert [entry["journal_id"] for entry in upcoming] == [outdoor_id, planning_id]
    outdoor, planning = upcoming
    assert outdoor["title"] == "Canyon trip"
    assert outdoor["is_planning"] is False
    assert "canyoning" in outdoor["subtypes"]
    assert outdoor["event_date_range"]["start"] is not None
    assert outdoor["event_date_range"]["end"] is not None
    assert planning["title"] == "Planning night"
    assert planning["is_planning"] is True
    assert planning["subtypes"] == []


async def test_totals_bucket_by_window_and_effective_type(
    authenticated_client,
    seeder: Seeder,
) -> None:
    now = datetime.now(UTC)
    # A canyoning trip 10 days ago counts in both rolling windows; the
    # dependency-added bushwalking/abseiling rows collapse to "canyoning".
    await seeder.create_incomplete_canyoning_journal(
        title="Canyon", start=now - timedelta(days=10)
    )
    # A plain outdoor journal 100 days ago counts in the 365-day window only.
    await seeder.create_outdoor_journal(
        title="Old walk", start=now - timedelta(days=100)
    )

    response = await authenticated_client.get(URL)

    assert response.status_code == 200
    totals = response.json()["data"]["attributes"]["activity_totals"]
    assert totals["last_30_days"] == {"canyoning": 1}
    assert totals["last_365_days"] == {"canyoning": 1, "outdoor_activity": 1}
    # Distinct journals, counted alongside the per-type buckets.
    assert totals["total_last_30_days"] == 1
    assert totals["total_last_365_days"] == 2


async def test_checked_out_gear_excludes_future_and_returned_checkouts(
    authenticated_client,
    seeder: Seeder,
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

    response = await authenticated_client.get(URL)

    assert response.status_code == 200
    gear = response.json()["data"]["attributes"]["checked_out_gear"]
    assert [entry["journal_id"] for entry in gear] == [open_id]
    entry = gear[0]
    assert entry["gear_item_id"] == rope
    assert entry["name"] == "Rope"
    assert entry["checked_out_since"] is not None


async def test_templates_done_grouped_by_type_with_counts_and_ids(
    authenticated_client,
    seeder: Seeder,
) -> None:
    now = datetime.now(UTC)
    template_id = await seeder.create_template(
        name="Empress Falls", template_type="canyoning"
    )
    stale_template = await seeder.create_template(
        name="Claustral", template_type="canyoning"
    )
    await seeder.create_abseiling_journal(
        title="First run", start=now - timedelta(days=30), template_id=template_id
    )
    await seeder.create_abseiling_journal(
        title="Second run", start=now - timedelta(days=10), template_id=template_id
    )
    # Done long ago: grouped all-time, but not counted as done recently.
    await seeder.create_abseiling_journal(
        title="Old run", start=now - timedelta(days=200), template_id=stale_template
    )
    # No template reference: not a "done" template row.
    await seeder.create_abseiling_journal(
        title="No template", start=now - timedelta(days=5)
    )

    response = await authenticated_client.get(URL)

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert attributes["templates_done"] == {
        "canyoning": [
            {"template_id": stale_template, "name": "Claustral", "done_count": 1},
            {"template_id": template_id, "name": "Empress Falls", "done_count": 2},
        ]
    }
    # Only Empress Falls falls inside the 30-day window, and it counts once
    # despite being done twice.
    assert attributes["templates_done_last_30_days"] == 1
