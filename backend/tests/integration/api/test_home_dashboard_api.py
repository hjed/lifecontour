"""Integration tests for the home dashboard REST endpoint.

Exercises ``GET /api/home-dashboard`` end-to-end through the real container and
the ``authenticated_client``. Every section is empty in this phase, so what is
asserted here is the envelope the later phases fill: the four sections arrive in
one call, the anchor follows the user's stored timezone, and a section that
cannot be read costs only itself — the response is still a 200 dashboard rather
than an error document.
"""

import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.core.dashboard.services.home_dashboard_service import HomeDashboardService
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.infrastructure.config import Settings
from app.main import create_app

URL = "/api/home-dashboard"
USER_ID = "test-user-123"
SECTIONS = ("summary", "agenda", "tasks", "upcoming_dates")

# Twenty-five hours apart, so one instant is never the same calendar date in
# both — which makes the anchoring assertions independent of when the suite runs.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14
FAR_WEST = "Pacific/Niue"  # UTC-11


def local_date(timezone: str) -> datetime.date:
    return datetime.datetime.now(ZoneInfo(timezone)).date()


@pytest.mark.asyncio
class TestTheSectionEnvelope:
    async def test_returns_all_four_sections_in_one_call(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(URL)

        assert response.status_code == 200
        document = response.json()
        assert document["data"]["type"] == "home-dashboards"
        assert document["data"]["id"] == USER_ID
        attributes = document["data"]["attributes"]
        assert set(attributes) == set(SECTIONS)
        for name in SECTIONS:
            assert attributes[name] == {"status": "ready", "data": {}}, name

    async def test_the_resource_links_to_itself(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(URL)

        assert response.status_code == 200
        assert response.json()["data"]["links"]["self"].endswith(URL)

    async def test_takes_no_date_parameters(
        self, authenticated_client: AsyncClient
    ) -> None:
        """The day is the server's to decide, so a supplied one changes nothing."""
        plain = await authenticated_client.get(URL)
        with_date = await authenticated_client.get(f"{URL}?date=2020-01-01")

        assert with_date.status_code == 200
        assert with_date.json()["meta"] == plain.json()["meta"]


@pytest.mark.asyncio
class TestTheAnchor:
    @pytest.mark.parametrize("timezone", [FAR_EAST, FAR_WEST])
    async def test_follows_the_users_stored_timezone(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        timezone: str,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=timezone)
        )

        before = local_date(timezone)
        response = await authenticated_client.get(URL)
        after = local_date(timezone)

        assert response.status_code == 200
        anchor = response.json()["meta"]["anchor"]
        assert anchor["timezone"] == timezone
        # Two readings straddle the request so a midnight crossing mid-test
        # cannot fail it, while still pinning the date to this zone.
        assert anchor["date"] in {before.isoformat(), after.isoformat()}

    async def test_the_two_zones_disagree_about_today(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """Proof the assertion above is about the zone and not about UTC.

        Twenty-five hours apart, the two users are never on the same date, so a
        UTC-anchored implementation could not satisfy both readings.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        east = (await authenticated_client.get(URL)).json()["meta"]["anchor"]["date"]

        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_WEST)
        )
        west = (await authenticated_client.get(URL)).json()["meta"]["anchor"]["date"]

        assert east != west

    async def test_falls_back_to_utc_when_nothing_is_stored(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(URL)

        assert response.json()["meta"]["anchor"]["timezone"] == "UTC"


@pytest.mark.asyncio
class TestASectionFailureCostsOnlyThatSection:
    @pytest.fixture
    def failing_tasks_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Break the tasks read for every request the container serves.

        Patched on the class because the service instance is built per request
        by Dishka. Phase 13 gives this section a real query; until then this is
        how the contract asserted in the unit tests is proven through HTTP.
        """

        async def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("tasks query blew up")

        monkeypatch.setattr(HomeDashboardService, "_load_tasks", boom)

    async def test_the_request_still_succeeds(
        self, authenticated_client: AsyncClient, failing_tasks_section: None
    ) -> None:
        response = await authenticated_client.get(URL)

        assert response.status_code == 200

    async def test_the_failure_is_reported_inside_data_not_as_errors(
        self, authenticated_client: AsyncClient, failing_tasks_section: None
    ) -> None:
        """JSON:API forbids data and errors together, so it cannot be an error."""
        document = (await authenticated_client.get(URL)).json()

        assert "errors" not in document
        assert document["data"]["attributes"]["tasks"] == {
            "status": "unavailable",
            "data": None,
        }

    async def test_the_other_three_sections_and_the_anchor_survive(
        self, authenticated_client: AsyncClient, failing_tasks_section: None
    ) -> None:
        document = (await authenticated_client.get(URL)).json()

        attributes = document["data"]["attributes"]
        for name in ("summary", "agenda", "upcoming_dates"):
            assert attributes[name]["status"] == "ready", name
        assert document["meta"]["anchor"]["date"] is not None


class TestAuthentication:
    def test_requires_authentication(self, test_settings: Settings) -> None:
        client = TestClient(create_app(settings=test_settings))

        response = client.get(URL, headers={"Host": "localhost"})

        assert response.status_code == 401
