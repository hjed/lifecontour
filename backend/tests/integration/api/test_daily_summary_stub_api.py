"""The test-only daily-summary stub, reached through settings and DI.

``ENABLE_TEST_DAILY_SUMMARY_STUB`` is how the e2e stack produces a *generated*
summary without a model: the ``DailySummaryService`` provider hands the service
a fixed response in place of a Gemini call. These tests drive the real REST
endpoints over the real container, so they fail if the flag stops reaching the
provider, and they pin the other half too — with the flag off and no key, both
summary endpoints and the dashboard answer the way an unconfigured backend
does, which is the wire shape the e2e "AI unconfigured" test serves.

``gemini_api_key`` is cleared in each test because ``Settings`` also reads the
environment, and a developer's exported key would otherwise reach a real model.
"""

from datetime import UTC, datetime

import pytest

from app.infrastructure.config import Settings
from app.infrastructure.di.journal import DAILY_SUMMARY_STUB_TEXT

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _today() -> str:
    # The test user has no saved timezone, so their day is the UTC day.
    return datetime.now(UTC).date().isoformat()


async def test_the_stub_generates_todays_summary_and_the_dashboard_reads_it(
    authenticated_client, clean_database, test_settings: Settings
) -> None:
    test_settings.gemini_api_key = ""
    test_settings.enable_test_daily_summary_stub = True

    response = await authenticated_client.post(
        f"/api/journals/daily-summary/{_today()}/regenerate"
    )

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]
    assert attributes["status"] == "generated"
    assert attributes["summary_text"] == DAILY_SUMMARY_STUB_TEXT

    dashboard = await authenticated_client.get("/api/home-dashboard")
    assert dashboard.status_code == 200
    summary = dashboard.json()["data"]["attributes"]["summary"]
    assert summary["status"] == "ready"
    assert summary["data"]["state"] == "generated"
    assert summary["data"]["summary_text"] == DAILY_SUMMARY_STUB_TEXT


async def test_without_the_stub_or_a_key_no_summary_is_produced(
    authenticated_client, clean_database, test_settings: Settings
) -> None:
    test_settings.gemini_api_key = ""
    test_settings.enable_test_daily_summary_stub = False

    read = await authenticated_client.get(f"/api/journals/daily-summary/{_today()}")
    regenerate = await authenticated_client.post(
        f"/api/journals/daily-summary/{_today()}/regenerate"
    )

    assert read.status_code == 200
    assert read.json() == {"data": None}
    assert regenerate.status_code == 200
    assert regenerate.json() == {"data": None}

    dashboard = await authenticated_client.get("/api/home-dashboard")
    summary = dashboard.json()["data"]["attributes"]["summary"]
    assert summary["status"] == "unavailable"
    assert summary["data"] is None
