"""Integration tests for the home dashboard REST endpoint.

Exercises ``GET /api/home-dashboard`` end-to-end through the real container and
the ``authenticated_client``.

Two things are asserted here. The **envelope** the later phases fill: the four
sections arrive in one call, the anchor follows the user's stored timezone, and a
section that cannot be read costs only itself — the response is still a 200
dashboard rather than an error document. And the **summary section**, against
real ``journal_daily_summaries`` rows in each status the column allows, because a
mapping that reads correctly against a mock can still be wrong about which day it
asked for or what the database gave back.
"""

import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dashboard.services.home_dashboard_service import HomeDashboardService
from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.infrastructure.config import Settings
from app.main import create_app

URL = "/api/home-dashboard"
USER_ID = "test-user-123"
SECTIONS = ("summary", "agenda", "tasks", "upcoming_dates")

# Distinctive enough that a test can assert it is absent from the whole document
# rather than only from the field it was expected in.
SUMMARY_TEXT = "A long day of climbing and two good conversations."
EASTERN_TEXT = "The summary written for the far-eastern day."

# Twenty-five hours apart, so one instant is never the same calendar date in
# both — which makes the anchoring assertions independent of when the suite runs.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14
FAR_WEST = "Pacific/Niue"  # UTC-11


def local_date(timezone: str) -> datetime.date:
    return datetime.datetime.now(ZoneInfo(timezone)).date()


@pytest.fixture
async def summary_repository(
    async_connection: AsyncConnection,
) -> SqlJournalDailySummaryRepository:
    """The real repository over the test's connection.

    The same connection the request reads through, injected by
    ``TestDatabaseProvider``, so a row written here is visible to the endpoint
    without a commit — and is rolled back with the rest of the test.
    """
    return SqlJournalDailySummaryRepository(async_connection)


async def write_summary(
    repository: SqlJournalDailySummaryRepository,
    summary_date: datetime.date,
    status: SummaryStatus,
    **overrides: object,
) -> None:
    """Put one real ``journal_daily_summaries`` row in front of the endpoint."""
    fields: dict[str, object] = {
        "summary_text": SUMMARY_TEXT,
        "journal_count": 4,
        "event_count": 2,
        "contact_count": 3,
        "mood_average": 7.5,
        # Generated now, so today's row is fresh whichever day the anchor lands
        # on; the staleness test overrides it.
        "generated_at": datetime.datetime.now(datetime.UTC),
    }
    fields.update(overrides)
    await repository.upsert(
        JournalDailySummary(
            user_id=USER_ID,
            summary_date=summary_date,
            status=status,
            **fields,  # type: ignore[arg-type]
        )
    )


async def write_todays_summary(
    repository: SqlJournalDailySummaryRepository,
    status: SummaryStatus,
    **overrides: object,
) -> None:
    """The same row on today and the days either side of it.

    A test cannot freeze the clock through HTTP, so it cannot know which date the
    endpoint will anchor on: reading "today" before the request and having
    midnight pass before the response would leave the row on the wrong day and
    fail a test the endpoint handled correctly. Writing the whole three-day
    window means whichever day the anchor lands on has this row waiting, which is
    the same trick the Phase 1 tests play by bracketing their assertions.

    It costs nothing in discrimination: no assertion here is about *which* day
    was chosen — that is ``TestTheAnchor``'s subject, and the unit tests pin it
    against a fixed instant.
    """
    utc_today = local_date("UTC")
    for offset in (-1, 0, 1):
        await write_summary(
            repository, utc_today + datetime.timedelta(days=offset), status, **overrides
        )


def empty_agenda(document: dict[str, Any]) -> dict[str, Any]:
    """The agenda a user with no events gets: ready, both days empty.

    Tomorrow's date is read off the document's own anchor rather than a clock,
    so a midnight crossing mid-test moves the expectation with the answer.
    """
    anchor = datetime.date.fromisoformat(document["meta"]["anchor"]["date"])
    tomorrow = anchor + datetime.timedelta(days=1)
    return {
        "status": "ready",
        "data": {
            "entries": [],
            "tomorrow": {"date": tomorrow.isoformat(), "entries": []},
        },
    }


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
        # This user has no summary row, so that section reports unavailable.
        # The agenda answers with an empty day — its own suite covers a populated
        # one — and the two Phases 11 and 13 have yet to fill answer with nothing.
        assert attributes["summary"] == {"status": "unavailable", "data": None}
        assert attributes["agenda"] == empty_agenda(document)
        for name in ("tasks", "upcoming_dates"):
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
        """The day is the server's to decide, so a supplied one is ignored.

        Asserted against *this* response rather than by comparing it with an
        unparameterised one: two requests can straddle midnight, and the
        comparison would then fail over a day boundary the endpoint handled
        correctly. This user has no stored timezone, so the anchor is UTC's day
        — bracketed either side of the call for the same reason.
        """
        before = local_date("UTC")
        response = await authenticated_client.get(f"{URL}?date=2020-01-01")
        after = local_date("UTC")

        assert response.status_code == 200
        anchor = response.json()["meta"]["anchor"]
        assert anchor["date"] != "2020-01-01"
        assert anchor["date"] in {before.isoformat(), after.isoformat()}


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
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
        failing_tasks_section: None,
    ) -> None:
        """A summary row is written so all three survivors have something to say."""
        await write_todays_summary(summary_repository, SummaryStatus.GENERATED)

        document = (await authenticated_client.get(URL)).json()

        attributes = document["data"]["attributes"]
        for name in ("summary", "agenda", "upcoming_dates"):
            assert attributes[name]["status"] == "ready", name
        assert document["meta"]["anchor"]["date"] is not None


@pytest.mark.asyncio
class TestASqlErrorDoesNotPoisonTheRemainingSections:
    """The SAVEPOINT contract, against a database rather than a raised exception.

    Every other failure test in this file injects a Python ``RuntimeError``,
    which never reaches PostgreSQL — so none of them exercises the reason the
    savepoints exist. A real failed statement leaves the transaction *aborted*,
    and every later query on the same connection fails with "current transaction
    is aborted" until something rolls back to a savepoint. Phase 1 built that
    machinery on the promise that the phases adding queries would prove it; the
    summary is the first query, so it is proved here.

    The proof needs a section that runs SQL *after* the broken one. The agenda
    now issues a real query of its own, which is what this test was waiting for:
    it is read straight after the summary, so if the rollback did not happen it
    is the section that would fail with "current transaction is aborted".
    """

    @pytest.fixture
    def summary_read_fails_in_the_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def divide_by_zero(
            self: HomeDashboardService, *_args: object, **_kwargs: object
        ) -> None:
            assert self.connection is not None
            await self.connection.execute(text("SELECT 1 / 0"))

        monkeypatch.setattr(HomeDashboardService, "_load_summary", divide_by_zero)

    async def test_the_broken_section_reports_unavailable(
        self,
        authenticated_client: AsyncClient,
        summary_read_fails_in_the_database: None,
    ) -> None:
        response = await authenticated_client.get(URL)

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["summary"] == {
            "status": "unavailable",
            "data": None,
        }

    async def test_a_later_section_can_still_query(
        self,
        authenticated_client: AsyncClient,
        summary_read_fails_in_the_database: None,
    ) -> None:
        """Without the rollback this is "current transaction is aborted".

        The agenda is the later section with a query of its own, and it is read
        immediately after the broken one — so its reaching *ready* at all is the
        assertion, whatever this user's empty day puts in it.
        """
        document = (await authenticated_client.get(URL)).json()

        assert document["data"]["attributes"]["agenda"] == empty_agenda(document)

    async def test_the_anchor_and_the_untouched_sections_survive(
        self,
        authenticated_client: AsyncClient,
        summary_read_fails_in_the_database: None,
    ) -> None:
        document = (await authenticated_client.get(URL)).json()

        assert "errors" not in document
        for name in ("tasks", "upcoming_dates"):
            assert document["data"]["attributes"][name]["status"] == "ready", name
        assert document["meta"]["anchor"]["date"] is not None


class TestAuthentication:
    def test_requires_authentication(self, test_settings: Settings) -> None:
        client = TestClient(create_app(settings=test_settings))

        response = client.get(URL, headers={"Host": "localhost"})

        assert response.status_code == 401


@pytest.mark.asyncio
class TestTheSummarySection:
    """The section against real rows, one per status the column allows.

    The check constraint on ``status`` means these five are the whole domain, so
    together with the no-row case below they are every state a user can be in.
    """

    @pytest.mark.parametrize(
        ("status", "expected_state"),
        [
            (SummaryStatus.GENERATED, "generated"),
            (SummaryStatus.PENDING, "generating"),
            (SummaryStatus.GENERATING, "generating"),
        ],
    )
    async def test_a_showable_status_arrives_ready_in_its_state(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
        status: SummaryStatus,
        expected_state: str,
    ) -> None:
        await write_todays_summary(summary_repository, status)

        section = (await authenticated_client.get(URL)).json()["data"]["attributes"][
            "summary"
        ]

        assert section["status"] == "ready"
        assert section["data"]["state"] == expected_state

    @pytest.mark.parametrize("status", [SummaryStatus.FAILED, SummaryStatus.DISABLED])
    async def test_an_unshowable_status_arrives_unavailable(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
        status: SummaryStatus,
    ) -> None:
        """A failed generation and a day below the threshold both read as W9."""
        await write_todays_summary(summary_repository, status)

        section = (await authenticated_client.get(URL)).json()["data"]["attributes"][
            "summary"
        ]

        assert section == {"status": "unavailable", "data": None}

    async def test_no_summary_at_all_arrives_unavailable(
        self, authenticated_client: AsyncClient
    ) -> None:
        """No row is written until a summary is attempted, or AI is configured."""
        response = await authenticated_client.get(URL)

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["summary"] == {
            "status": "unavailable",
            "data": None,
        }

    async def test_the_rest_of_the_page_survives_a_missing_summary(
        self, authenticated_client: AsyncClient
    ) -> None:
        """The specification's ruling, exercised through HTTP with no row."""
        attributes = (await authenticated_client.get(URL)).json()["data"]["attributes"]

        for name in ("agenda", "tasks", "upcoming_dates"):
            assert attributes[name]["status"] == "ready", name

    async def test_a_generated_summary_carries_its_prose_and_four_counters(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        """W7's body and W10's Journals / Events / Contacts / Avg Mood."""
        await write_todays_summary(summary_repository, SummaryStatus.GENERATED)

        payload = (await authenticated_client.get(URL)).json()["data"]["attributes"][
            "summary"
        ]["data"]

        assert payload == {
            "state": "generated",
            "summary_text": SUMMARY_TEXT,
            "journal_count": 4,
            "event_count": 2,
            "contact_count": 3,
            "mood_average": 7.5,
        }

    @pytest.mark.parametrize(
        "status", [SummaryStatus.PENDING, SummaryStatus.GENERATING]
    )
    async def test_prose_from_an_earlier_generation_never_reaches_the_page(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
        status: SummaryStatus,
    ) -> None:
        """Invalidation keeps the old text in the row; the wire must not show it."""
        await write_todays_summary(summary_repository, status)

        document = (await authenticated_client.get(URL)).json()

        assert document["data"]["attributes"]["summary"]["data"]["summary_text"] is None
        assert SUMMARY_TEXT not in json.dumps(document)

    async def test_a_summary_generated_before_today_is_withheld_as_generating(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        """A generated row from an earlier day must not be served as today's.

        Two days old, so it is stale whichever of the bracketed dates the
        anchor lands on. The page shows the generating state — whose exit is
        the reader's own Regenerate control — and keeps the counters.
        """
        two_days_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2)
        await write_todays_summary(
            summary_repository, SummaryStatus.GENERATED, generated_at=two_days_ago
        )

        document = (await authenticated_client.get(URL)).json()

        section = document["data"]["attributes"]["summary"]
        assert section["status"] == "ready"
        assert section["data"]["state"] == "generating"
        assert section["data"]["summary_text"] is None
        assert section["data"]["journal_count"] == 4
        assert SUMMARY_TEXT not in json.dumps(document)

    async def test_withholding_a_stale_summary_writes_nothing(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        """A dashboard load must not write: the stale row is left exactly as it was."""
        two_days_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2)
        await write_todays_summary(
            summary_repository, SummaryStatus.GENERATED, generated_at=two_days_ago
        )

        document = (await authenticated_client.get(URL)).json()

        anchor = datetime.date.fromisoformat(document["meta"]["anchor"]["date"])
        row = await summary_repository.find_by_user_and_date(USER_ID, anchor)
        assert row is not None
        assert row.status is SummaryStatus.GENERATED
        assert row.summary_text == SUMMARY_TEXT
        assert row.generated_at == two_days_ago

    async def test_a_day_with_no_moods_recorded_reports_no_average(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        """The NUMERIC column is nullable, and null must survive the round trip."""
        await write_todays_summary(
            summary_repository, SummaryStatus.GENERATED, mood_average=None
        )

        payload = (await authenticated_client.get(URL)).json()["data"]["attributes"][
            "summary"
        ]["data"]

        assert payload["mood_average"] is None


@pytest.mark.asyncio
class TestTheSummaryFollowsTheUsersDay:
    async def test_returns_the_summary_stored_against_the_anchor_date(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        """The row that comes back is the one filed under the day being reported.

        A summary is stored on three consecutive days, each naming its own date,
        so whichever day the request lands on the answer identifies it — and a
        midnight crossing mid-test changes which row is expected rather than
        failing the test.

        The user is on UTC+14, whose calendar date differs from UTC's for
        fourteen hours in every twenty-four; for the other ten the two coincide,
        and a UTC-anchored implementation would pass this unnoticed. That is why
        *which* day the anchor picks is not asserted here — ``TestTheAnchor``
        owns it, and the unit tests pin it against a fixed instant. What this
        adds is the join: the summary and the anchor agree about the day.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        utc_today = local_date("UTC")
        days = [utc_today + datetime.timedelta(days=offset) for offset in (-1, 0, 1)]
        for day in days:
            await write_summary(
                summary_repository,
                day,
                SummaryStatus.GENERATED,
                summary_text=f"{EASTERN_TEXT} {day.isoformat()}",
            )

        before = local_date(FAR_EAST)
        document = (await authenticated_client.get(URL)).json()
        after = local_date(FAR_EAST)

        anchor = document["meta"]["anchor"]["date"]
        assert anchor in {before.isoformat(), after.isoformat()}
        assert (
            document["data"]["attributes"]["summary"]["data"]["summary_text"]
            == f"{EASTERN_TEXT} {anchor}"
        )

    async def test_a_summary_for_another_day_is_not_todays(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        """Yesterday's summary is not a stand-in for one today does not have."""
        await write_summary(
            summary_repository,
            local_date("UTC") - datetime.timedelta(days=1),
            SummaryStatus.GENERATED,
        )

        section = (await authenticated_client.get(URL)).json()["data"]["attributes"][
            "summary"
        ]

        assert section == {"status": "unavailable", "data": None}


@pytest.mark.asyncio
class TestTheDashboardNeverGeneratesASummary:
    """The table is untouched by a page load.

    **These two do not, on their own, prove the dashboard avoids the generating
    path.** ``get_or_generate`` returns early when no Gemini key is configured,
    and the test settings configure none, so swapping ``DailySummaryService``
    back into ``DashboardProvider`` would leave both of these green. The test
    that actually holds that line is the unit one
    (``test_never_asks_for_a_summary_to_be_generated``), which pins the calls the
    service makes.

    What these two do prove is the property a reader cares about, at the level it
    matters: after loading the page, the stored summary is exactly what it was
    before — nothing created, nothing advanced, nothing overwritten.
    """

    async def test_loading_the_page_leaves_an_empty_table_empty(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        today = local_date("UTC")

        await authenticated_client.get(URL)
        await authenticated_client.get(URL)

        assert (await summary_repository.find_by_user_and_date(USER_ID, today)) is None

    async def test_an_existing_summary_is_left_exactly_as_it_was(
        self,
        authenticated_client: AsyncClient,
        summary_repository: SqlJournalDailySummaryRepository,
    ) -> None:
        """PENDING is the status the generating path would have moved on from.

        It marks a summary as due for regeneration, so a dashboard that reached
        for ``get_or_generate`` would leave this row on GENERATING or GENERATED
        rather than where it found it.
        """
        today = local_date("UTC")
        await write_summary(summary_repository, today, SummaryStatus.PENDING)

        await authenticated_client.get(URL)

        stored = await summary_repository.find_by_user_and_date(USER_ID, today)
        assert stored is not None
        assert stored.status is SummaryStatus.PENDING
        assert stored.summary_text == SUMMARY_TEXT
