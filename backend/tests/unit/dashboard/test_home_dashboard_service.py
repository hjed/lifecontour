"""Unit tests for HomeDashboardService.

Pins the three rules the later phases build on: the payload declares all four
sections whether or not they have anything in them, "today" is the user's local
date and never UTC's, and one section failing costs only that section — the
others still answer, and its SAVEPOINT is rolled back so the shared connection
survives to serve them.

The summary is the first section with a query of its own, so this file also pins
what the service does with it — which day it asks for, that it only ever reads,
and that its absence is an ordinary answer rather than an incident.
"""

import datetime
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.contacts.entities import ImportantDate, SummaryStatus
from core_shared.models.contacts.important_date_occurrence import (
    ImportantDateOccurrence,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.date_window import upcoming_window
from core_shared.models.journals.daily_summary import JournalDailySummary
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.importance import ContactImportance
from app.core.contacts.models.upcoming_dates import (
    UpcomingContactDate,
    UpcomingContactDates,
    UpcomingDateContact,
)
from app.core.dashboard.models.sections import (
    AgendaDay,
    AgendaSectionData,
    DashboardSummaryState,
    HomeDashboard,
    SectionStatus,
    UpcomingDatesSectionData,
)
from app.core.dashboard.services.home_dashboard_service import HomeDashboardService
from app.core.journal.models.agenda import AgendaEntry
from app.core.journal.services.journal_date_resolver import JournalDateResolver

pytestmark = pytest.mark.unit

USER_ID = "test-user-123"
SECTIONS = ("summary", "agenda", "tasks", "upcoming_dates")
SERVICE_LOGGER = HomeDashboardService.__module__

# 00:30 on 31 July in Sydney (+10), while UTC is still on the 30th — the instant
# that tells a local reading apart from a UTC one.
JUST_PAST_SYDNEY_MIDNIGHT = datetime.datetime(2026, 7, 30, 14, 30, tzinfo=datetime.UTC)

# The day the Sydney instant above lands on, and the day every section windows on.
ANCHOR = datetime.date(2026, 7, 31)

UPCOMING_BIRTHDAY = UpcomingContactDate(
    occurrence=ImportantDateOccurrence(
        important_date=ImportantDate(
            id=1,
            contact_id=7,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.DAY_MONTH,
            month=8,
            day=2,
        ),
        occurs_on=datetime.date(2026, 8, 2),
        days_away=2,
        years=None,
        observed_for_leap_day=False,
    ),
    contact=UpcomingDateContact(id=7, display_name="Ada Lovelace", photo_url=None),
    importance=ContactImportance(
        contact_id=7,
        is_favourite=False,
        journal_count_30d=0,
        activity_count_30d=0,
        last_activity_at=None,
    ),
)


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def date_resolver(mock_settings_repo: AsyncMock) -> JournalDateResolver:
    """The real resolver over a stubbed settings row.

    Real rather than mocked so the timezone rules under test are the ones that
    run in production, not a second copy of them.
    """
    return JournalDateResolver(user_settings_repo=mock_settings_repo)


@pytest.fixture
def mock_summary_repo() -> AsyncMock:
    """A summary repository holding a generated summary for any day asked for.

    A generated row by default so the envelope tests still see four ready
    sections; the tests that care about the other statuses set their own.
    """
    repo = AsyncMock()
    repo.find_by_user_and_date.return_value = JournalDailySummary(
        user_id=USER_ID,
        summary_date=datetime.date(2026, 7, 31),
        summary_text="A long day.",
        status=SummaryStatus.GENERATED,
        # Generated now, so it is fresh whichever day the service anchors on.
        generated_at=datetime.datetime.now(datetime.UTC),
    )
    return repo


def generated_summary(generated_at: datetime.datetime) -> JournalDailySummary:
    """Today's generated row, written at ``generated_at``."""
    return JournalDailySummary(
        user_id=USER_ID,
        summary_date=datetime.date(2026, 7, 31),
        summary_text="A long day.",
        status=SummaryStatus.GENERATED,
        generated_at=generated_at,
    )


@pytest.fixture
def connection() -> MagicMock:
    """A connection that passes ``savepoint``'s isinstance check.

    ``savepoint`` no-ops for anything that is not a real ``AsyncConnection``, so
    a bare mock would let the guard silently stop wrapping sections without a
    test noticing. ``begin_nested`` is awaited rather than called, and the spec
    does not declare it a coroutine function, so it is replaced by hand.
    """
    connection = MagicMock(spec=AsyncConnection)
    connection.begin_nested = AsyncMock(return_value=AsyncMock())
    return connection


def agenda_entry(
    journal_id: int,
    hour: int,
    *,
    all_day: bool = False,
    cancelled: bool = False,
    day: datetime.date = datetime.date(2026, 7, 31),
) -> AgendaEntry:
    """One entry on 31 July 2026 (or ``day``), written as the hour a reader sees."""
    starts_at = datetime.datetime.combine(day, datetime.time(hour), tzinfo=datetime.UTC)
    return AgendaEntry(
        journal_id=journal_id,
        title=f"Event {journal_id}",
        is_all_day=all_day,
        starts_at=starts_at,
        ends_at=starts_at + datetime.timedelta(hours=1),
        is_cancelled=cancelled,
    )


@pytest.fixture
def mock_agenda_repo() -> AsyncMock:
    """An agenda repository answering with one ordinary timed entry."""
    repo = AsyncMock()
    repo.list_entries_in_window.return_value = [agenda_entry(1, 9)]
    return repo


@pytest.fixture
def mock_upcoming_dates_service() -> AsyncMock:
    """The contacts read, answering with an empty window by default.

    Mocked rather than built from repositories because what this suite asserts
    about it is the *wiring* — that the section is asked, with the dashboard's
    own anchor, and that its failure stays local. What it returns is the
    contacts domain's business and has its own tests.
    """
    service = AsyncMock()
    service.upcoming_dates.return_value = UpcomingContactDates(
        window=upcoming_window(ANCHOR), dates=()
    )
    return service


@pytest.fixture
def service(
    date_resolver: JournalDateResolver,
    mock_summary_repo: AsyncMock,
    mock_agenda_repo: AsyncMock,
    mock_upcoming_dates_service: AsyncMock,
    connection: MagicMock,
) -> HomeDashboardService:
    return HomeDashboardService(
        date_resolver=date_resolver,
        summary_repo=mock_summary_repo,
        agenda_repo=mock_agenda_repo,
        upcoming_dates_service=mock_upcoming_dates_service,
        connection=connection,
    )


def sections_of(dashboard: HomeDashboard) -> dict[str, Any]:
    return {name: getattr(dashboard, name) for name in SECTIONS}


class TestTheFourSectionEnvelope:
    async def test_declares_every_section_whatever_each_one_holds(
        self, service: HomeDashboardService
    ) -> None:
        """Later phases fill this contract; none of them adds a section to it.

        The one still without a query answers with an empty payload, which is
        itself the assertion: such a section is *ready and holding nothing*,
        never absent from the projection.
        """
        dashboard = await service.dashboard(USER_ID)

        assert set(sections_of(dashboard)) == set(SECTIONS)
        for name, section in sections_of(dashboard).items():
            assert section.status is SectionStatus.READY, name
            assert section.data is not None, name

    async def test_identifies_the_user_the_projection_belongs_to(
        self, service: HomeDashboardService
    ) -> None:
        dashboard = await service.dashboard(USER_ID)

        assert dashboard.user_id == USER_ID


class TestTheAnchor:
    async def test_is_the_users_local_today_not_utcs(
        self, service: HomeDashboardService, mock_settings_repo: AsyncMock
    ) -> None:
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        dashboard = await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert dashboard.anchor_date == datetime.date(2026, 7, 31)
        assert JUST_PAST_SYDNEY_MIDNIGHT.date() == datetime.date(2026, 7, 30)
        assert dashboard.timezone == "Australia/Sydney"

    async def test_reports_the_resolved_zone_when_the_stored_one_is_nonsense(
        self, service: HomeDashboardService, mock_settings_repo: AsyncMock
    ) -> None:
        """The column accepts any string, and the payload must not echo a lie.

        A surface labelling itself with the timezone the dates were computed in
        would otherwise say "Mars/Olympus" over dates that are really UTC's.
        """
        mock_settings_repo.get_timezone.return_value = "Mars/Olympus"

        dashboard = await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert dashboard.timezone == "UTC"
        assert dashboard.anchor_date == datetime.date(2026, 7, 30)

    async def test_is_read_once_for_the_whole_dashboard(
        self, service: HomeDashboardService, mock_settings_repo: AsyncMock
    ) -> None:
        """Four sections share one timezone, so they share one settings read."""
        await service.dashboard(USER_ID)

        mock_settings_repo.get_timezone.assert_awaited_once_with(USER_ID)

    async def test_a_failure_resolving_it_is_not_a_section_failure(
        self, service: HomeDashboardService, mock_settings_repo: AsyncMock
    ) -> None:
        """Every window depends on the anchor, so there is nothing to degrade to."""
        mock_settings_repo.get_timezone.side_effect = RuntimeError("settings are down")

        with pytest.raises(RuntimeError, match="settings are down"):
            await service.dashboard(USER_ID)


class TestPerSectionIsolation:
    @pytest.fixture
    def failing_agenda(
        self, service: HomeDashboardService, monkeypatch: pytest.MonkeyPatch
    ) -> HomeDashboardService:
        async def boom(*_args: object, **_kwargs: object) -> AgendaSectionData:
            raise RuntimeError("agenda query blew up")

        monkeypatch.setattr(service, "_load_agenda", boom)
        return service

    async def test_the_failing_section_reports_unavailable(
        self, failing_agenda: HomeDashboardService
    ) -> None:
        dashboard = await failing_agenda.dashboard(USER_ID)

        assert dashboard.agenda.status is SectionStatus.UNAVAILABLE
        assert dashboard.agenda.data is None

    async def test_the_other_three_sections_still_answer(
        self, failing_agenda: HomeDashboardService
    ) -> None:
        dashboard = await failing_agenda.dashboard(USER_ID)

        others = {
            name: section
            for name, section in sections_of(dashboard).items()
            if name != "agenda"
        }
        for name, section in others.items():
            assert section.status is SectionStatus.READY, name

    async def test_the_anchor_survives_a_section_failure(
        self, failing_agenda: HomeDashboardService, mock_settings_repo: AsyncMock
    ) -> None:
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        dashboard = await failing_agenda.dashboard(
            USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT
        )

        assert dashboard.anchor_date == datetime.date(2026, 7, 31)

    async def test_every_section_is_read_inside_its_own_savepoint(
        self, service: HomeDashboardService, connection: MagicMock
    ) -> None:
        """The four sections share one connection, so each needs its own escape.

        Without the SAVEPOINT a failed query would leave the transaction
        aborted and every section after it would fail too — which is the
        promise this phase makes, tested before the sections have queries.
        """
        await service.dashboard(USER_ID)

        assert connection.begin_nested.await_count == len(SECTIONS)
        assert connection.begin_nested.return_value.commit.await_count == len(SECTIONS)

    async def test_a_failing_section_rolls_its_savepoint_back(
        self, failing_agenda: HomeDashboardService, connection: MagicMock
    ) -> None:
        await failing_agenda.dashboard(USER_ID)

        nested = connection.begin_nested.return_value
        assert nested.rollback.await_count == 1
        assert nested.commit.await_count == len(SECTIONS) - 1

    async def test_a_missing_connection_is_tolerated(
        self,
        date_resolver: JournalDateResolver,
        mock_summary_repo: AsyncMock,
        mock_agenda_repo: AsyncMock,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """``savepoint(None)`` no-ops, so the guard is still the guard."""
        service = HomeDashboardService(
            date_resolver=date_resolver,
            summary_repo=mock_summary_repo,
            agenda_repo=mock_agenda_repo,
            upcoming_dates_service=mock_upcoming_dates_service,
            connection=None,
        )

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.tasks.status is SectionStatus.READY


class TestTheAnchorTimezoneObject:
    async def test_the_service_hands_sections_the_anchor_and_a_zoneinfo(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Section loaders window on a ``ZoneInfo``; the string is for the wire."""
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"
        seen: list[tuple[str, datetime.date, ZoneInfo]] = []

        async def record(
            user_id: str, anchor: datetime.date, tz: ZoneInfo
        ) -> AgendaSectionData:
            seen.append((user_id, anchor, tz))
            return AgendaSectionData(
                tomorrow=AgendaDay(date=anchor + datetime.timedelta(days=1))
            )

        monkeypatch.setattr(service, "_load_agenda", record)

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert seen == [
            (USER_ID, datetime.date(2026, 7, 31), ZoneInfo("Australia/Sydney"))
        ]


class TestTheSummarySection:
    """What the service asks the repository for, and what it does with it.

    The mapping itself is tested in ``test_summary_section.py``; what belongs
    here is the part only the service can get wrong — reading the *user's* day
    rather than the server's, never generating, and degrading alone.
    """

    async def test_reads_the_summary_for_the_users_local_today(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """A UTC-anchored read would fetch the previous day's summary here."""
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        mock_summary_repo.find_by_user_and_date.assert_awaited_once_with(
            USER_ID, datetime.date(2026, 7, 31)
        )

    async def test_carries_the_summary_the_row_holds(
        self, service: HomeDashboardService
    ) -> None:
        dashboard = await service.dashboard(USER_ID)

        assert dashboard.summary.status is SectionStatus.READY
        assert dashboard.summary.data is not None
        assert dashboard.summary.data.state is DashboardSummaryState.GENERATED
        assert dashboard.summary.data.summary_text == "A long day."

    async def test_withholds_a_summary_generated_before_the_users_today(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """At 00:30 in Sydney, a summary from 23:00 is yesterday's — and stale.

        The specification says a summary not generated today in the user's
        timezone must not be served; the dashboard cannot regenerate it (a page
        load must not write), so it shows the state whose exit is the reader's
        own Regenerate control, exactly as it does for an invalidated row.
        """
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"
        mock_summary_repo.find_by_user_and_date.return_value = generated_summary(
            datetime.datetime(2026, 7, 30, 13, 0, tzinfo=datetime.UTC)
        )

        dashboard = await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert dashboard.summary.status is SectionStatus.READY
        assert dashboard.summary.data is not None
        assert dashboard.summary.data.state is DashboardSummaryState.GENERATING
        assert dashboard.summary.data.summary_text is None

    async def test_serves_a_summary_generated_after_the_users_midnight(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Twenty minutes into the Sydney day is today, however UTC counts it."""
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"
        mock_summary_repo.find_by_user_and_date.return_value = generated_summary(
            datetime.datetime(2026, 7, 30, 14, 10, tzinfo=datetime.UTC)
        )

        dashboard = await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert dashboard.summary.data is not None
        assert dashboard.summary.data.state is DashboardSummaryState.GENERATED
        assert dashboard.summary.data.summary_text == "A long day."

    async def test_judges_freshness_in_the_users_zone_not_utcs(
        self, service: HomeDashboardService, mock_summary_repo: AsyncMock
    ) -> None:
        """The instant Sydney found stale is the same UTC day for a UTC user."""
        mock_summary_repo.find_by_user_and_date.return_value = generated_summary(
            datetime.datetime(2026, 7, 30, 13, 0, tzinfo=datetime.UTC)
        )

        dashboard = await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert dashboard.summary.data is not None
        assert dashboard.summary.data.state is DashboardSummaryState.GENERATED

    async def test_a_stale_summary_is_still_only_read(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Withholding is a reading, not a write: the row is left as it was."""
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"
        mock_summary_repo.find_by_user_and_date.return_value = generated_summary(
            datetime.datetime(2026, 7, 30, 13, 0, tzinfo=datetime.UTC)
        )

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        mock_summary_repo.upsert.assert_not_called()
        mock_summary_repo.update_status.assert_not_called()
        mock_summary_repo.invalidate_for_date.assert_not_called()

    async def test_reports_unavailable_when_the_user_has_no_summary(
        self, service: HomeDashboardService, mock_summary_repo: AsyncMock
    ) -> None:
        """The ordinary state of a day below the threshold, or of no AI at all."""
        mock_summary_repo.find_by_user_and_date.return_value = None

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.summary.status is SectionStatus.UNAVAILABLE
        assert dashboard.summary.data is None

    async def test_having_nothing_to_show_is_not_logged_as_a_failure(
        self,
        service: HomeDashboardService,
        mock_summary_repo: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A user without a summary is not an incident, so it warns about nothing.

        The distinction matters because the *other* route to an unavailable
        section — a query that raised — must stay loud enough to notice, and a
        log that cries wolf on every summary-less day is one nobody reads.

        Read through ``caplog`` rather than ``structlog.testing.capture_logs``:
        the application configures structlog to cache its bound loggers, so once
        anything in the process has logged, swapping the processor chain no
        longer intercepts and the capture silently returns nothing. That made
        this assertion pass or fail on test *ordering*.
        """
        mock_summary_repo.find_by_user_and_date.return_value = None

        with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
            await service.dashboard(USER_ID)

        assert caplog.records == []

    async def test_a_query_that_raises_is_still_logged(
        self,
        service: HomeDashboardService,
        mock_summary_repo: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_summary_repo.find_by_user_and_date.side_effect = RuntimeError("db is down")

        with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
            dashboard = await service.dashboard(USER_ID)

        assert dashboard.summary.status is SectionStatus.UNAVAILABLE
        assert len(caplog.records) == 1
        assert '"section": "summary"' in caplog.records[0].getMessage()

    async def test_a_summary_failure_costs_only_the_summary(
        self, service: HomeDashboardService, mock_summary_repo: AsyncMock
    ) -> None:
        """The specification's ruling: a failed summary must not take the page."""
        mock_summary_repo.find_by_user_and_date.side_effect = RuntimeError("db is down")

        dashboard = await service.dashboard(USER_ID)

        for name in ("agenda", "tasks", "upcoming_dates"):
            assert getattr(dashboard, name).status is SectionStatus.READY, name
        assert dashboard.anchor_date is not None

    async def test_never_asks_for_a_summary_to_be_generated(
        self, service: HomeDashboardService, mock_summary_repo: AsyncMock
    ) -> None:
        """The dashboard reads; it does not produce.

        ``DailySummaryService.get_or_generate`` writes a DISABLED or GENERATING
        row and then calls Gemini, so the read path is pinned to the repository
        to keep a page load from mutating anything.
        """
        await service.dashboard(USER_ID)

        touched = {name for name, _args, _kwargs in mock_summary_repo.mock_calls}
        assert touched == {"find_by_user_and_date"}


class TestTheAgendaSection:
    """What the service asks the agenda repository for, and what it does with it.

    The window is the subject here rather than the SQL: a query that is right
    about journals can still be asking about UTC's day, and near local midnight
    those are different days with different events in them.
    """

    async def test_asks_for_the_users_local_day_not_utcs(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        today = mock_agenda_repo.list_entries_in_window.await_args_list[0]
        window = today.kwargs["window"]
        sydney = ZoneInfo("Australia/Sydney")
        assert today.kwargs["anchor"] == datetime.date(2026, 7, 31)
        assert window.start == datetime.datetime(2026, 7, 31, tzinfo=sydney)
        assert JUST_PAST_SYDNEY_MIDNIGHT.date() == datetime.date(2026, 7, 30)

    async def test_the_window_ends_at_the_last_microsecond_of_the_local_day(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        """Inclusive at both ends, so an event at 23:59 is still today's.

        Built from the *next* day's midnight rather than ``time.max``, which is
        what ``local_day_window`` exists to get right in a zone whose clocks go
        back at midnight.
        """
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        today = mock_agenda_repo.list_entries_in_window.await_args_list[0]
        window = today.kwargs["window"]
        sydney = ZoneInfo("Australia/Sydney")
        next_midnight = datetime.datetime(2026, 8, 1, tzinfo=sydney)
        assert window.end == next_midnight - datetime.timedelta(microseconds=1)

    async def test_asks_only_about_the_acting_user(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        await service.dashboard(USER_ID)

        calls = mock_agenda_repo.list_entries_in_window.await_args_list
        assert calls, "the agenda was never read"
        assert all(call.args[0] == USER_ID for call in calls)

    async def test_returns_the_entries_in_the_agendas_order(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        """The repository's order is not the card's; the service applies the rule.

        Handed back deliberately jumbled, so a service that passed the rows
        through untouched would fail here rather than in an e2e three phases on.
        """
        mock_agenda_repo.list_entries_in_window.return_value = [
            agenda_entry(1, 17),
            agenda_entry(2, 9),
            agenda_entry(3, 0, all_day=True),
        ]

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.data is not None
        assert [e.journal_id for e in dashboard.agenda.data.entries] == [3, 2, 1]

    async def test_a_day_with_nothing_on_it_is_ready_and_empty(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        """Empty is an answer, and it must not read as *unavailable*.

        The card renders one quiet line for an empty day and a different quiet
        line when the section could not be read, so the two have to arrive
        differently.
        """
        mock_agenda_repo.list_entries_in_window.return_value = []

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.status is SectionStatus.READY
        assert dashboard.agenda.data is not None
        assert dashboard.agenda.data.entries == ()

    async def test_a_failing_query_costs_only_the_agenda(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        mock_agenda_repo.list_entries_in_window.side_effect = RuntimeError("db is down")

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.status is SectionStatus.UNAVAILABLE
        assert dashboard.agenda.data is None
        for name in ("summary", "tasks", "upcoming_dates"):
            assert getattr(dashboard, name).status is SectionStatus.READY, name


class TestTomorrow:
    """Tomorrow rides inside the agenda payload, read the same way as today.

    Open decision 5 is settled in favour of one round trip: the service asks the
    same repository the same question about the next local day and hands both
    answers back in one section. The tests here are about *which* day that is —
    the user's local tomorrow, not UTC's — and about the answer arriving in the
    same form as today's, because the disclosure renders it in the same form.
    """

    SYDNEY = ZoneInfo("Australia/Sydney")
    LOCAL_TOMORROW = datetime.date(2026, 8, 1)

    async def test_is_the_users_local_tomorrow_not_utcs(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        """Just past Sydney midnight on 31 July, tomorrow is 1 August.

        UTC is still on the 30th, so a UTC reading would ask about the 31st and
        call it tomorrow — and the boundary is a month end, so a date built by
        adding one to the day number would be wrong in a second way.
        """
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        tomorrow = mock_agenda_repo.list_entries_in_window.await_args_list[1]
        assert tomorrow.kwargs["anchor"] == self.LOCAL_TOMORROW
        assert tomorrow.kwargs["window"].start == datetime.datetime(
            2026, 8, 1, tzinfo=self.SYDNEY
        )

    async def test_its_window_ends_at_the_last_microsecond_of_that_day(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        window = mock_agenda_repo.list_entries_in_window.await_args_list[1].kwargs[
            "window"
        ]
        day_after = datetime.datetime(2026, 8, 2, tzinfo=self.SYDNEY)
        assert window.end == day_after - datetime.timedelta(microseconds=1)

    async def test_is_read_once_after_today_and_nothing_else_is(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        """Exactly two reads: today, then tomorrow.

        Not three — the agenda is two days, not a week — and not one wide read
        split afterwards, because a multi-day event overlapping both days
        belongs on both, which one window cannot say.
        """
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        anchors = [
            call.kwargs["anchor"]
            for call in mock_agenda_repo.list_entries_in_window.await_args_list
        ]
        assert anchors == [datetime.date(2026, 7, 31), datetime.date(2026, 8, 1)]

    async def test_carries_the_date_it_was_windowed_on(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
    ) -> None:
        """The disclosure labels itself from this, not from the browser's clock."""
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        dashboard = await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert dashboard.agenda.data is not None
        assert dashboard.agenda.data.tomorrow.date == self.LOCAL_TOMORROW
        assert dashboard.anchor_date == datetime.date(2026, 7, 31)

    async def test_its_entries_come_back_in_the_agendas_order(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        """W20: the same form as today, which includes the same order."""
        tomorrow = self.LOCAL_TOMORROW
        mock_agenda_repo.list_entries_in_window.side_effect = [
            [agenda_entry(1, 9)],
            [
                agenda_entry(11, 17, day=tomorrow),
                agenda_entry(12, 9, day=tomorrow),
                agenda_entry(13, 0, all_day=True, day=tomorrow),
            ],
        ]

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.data is not None
        ordered = [e.journal_id for e in dashboard.agenda.data.tomorrow.entries]
        assert ordered == [13, 12, 11]

    async def test_todays_and_tomorrows_entries_do_not_mix(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        mock_agenda_repo.list_entries_in_window.side_effect = [
            [agenda_entry(1, 9)],
            [agenda_entry(11, 9, day=self.LOCAL_TOMORROW)],
        ]

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.data is not None
        assert [e.journal_id for e in dashboard.agenda.data.entries] == [1]
        assert [e.journal_id for e in dashboard.agenda.data.tomorrow.entries] == [11]

    async def test_the_count_is_what_the_repository_returned_cancelled_included(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        """W19's count is the length of the list, and nothing is filtered on the
        way to it: a cancelled entry is shown marked when the day is expanded,
        so it is counted when the day is collapsed.
        """
        tomorrow = self.LOCAL_TOMORROW
        mock_agenda_repo.list_entries_in_window.side_effect = [
            [agenda_entry(1, 9, cancelled=True)],
            [
                agenda_entry(11, 9, day=tomorrow),
                agenda_entry(12, 10, day=tomorrow, cancelled=True),
                agenda_entry(13, 11, day=tomorrow),
            ],
        ]

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.data is not None
        agenda = dashboard.agenda.data
        assert len(agenda.tomorrow.entries) == 3
        assert [e.is_cancelled for e in agenda.tomorrow.entries] == [
            False,
            True,
            False,
        ]
        assert [e.is_cancelled for e in agenda.entries] == [True]

    async def test_nothing_tomorrow_is_a_ready_agenda_with_an_empty_day(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        """The disclosure shows a zero count and an empty line, not nothing."""
        mock_agenda_repo.list_entries_in_window.side_effect = [
            [agenda_entry(1, 9)],
            [],
        ]

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.status is SectionStatus.READY
        assert dashboard.agenda.data is not None
        assert dashboard.agenda.data.tomorrow.entries == ()
        assert len(dashboard.agenda.data.entries) == 1

    async def test_a_failure_reading_it_costs_only_the_agenda(
        self, service: HomeDashboardService, mock_agenda_repo: AsyncMock
    ) -> None:
        """Both days are one section: half an agenda would be a payload that
        looked complete while quietly missing a day, so the section degrades
        whole and the other three still answer.
        """
        mock_agenda_repo.list_entries_in_window.side_effect = [
            [agenda_entry(1, 9)],
            RuntimeError("db is down"),
        ]

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.agenda.status is SectionStatus.UNAVAILABLE
        assert dashboard.agenda.data is None
        for name in ("summary", "tasks", "upcoming_dates"):
            assert getattr(dashboard, name).status is SectionStatus.READY, name


class TestTheUpcomingDatesSection:
    """The section is read through the shared contacts service, not its own query."""

    async def test_the_whole_page_is_read_as_at_one_instant(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """A pinned ``now`` must pin the ranking as well as the window.

        The upcoming-dates section is ordered within a day by importance
        signals, and those are counted over the thirty days back from an
        instant. Handing down only the *day* left that instant to be sampled
        again inside the contacts service, so a caller who pinned ``now`` got a
        window fixed to one moment and a tie-break computed from another —
        which is not the single as-at snapshot this projection is supposed to
        be. Raised by the review on #1407.

        Sydney rather than UTC so the day and the instant are visibly different
        things: the anchor is the 31st while the instant is still the 30th.
        """
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        mock_upcoming_dates_service.upcoming_dates.assert_awaited_once_with(
            USER_ID, today=ANCHOR, now=JUST_PAST_SYDNEY_MIDNIGHT
        )

    async def test_an_unpinned_page_still_shares_one_instant(
        self,
        service: HomeDashboardService,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """The ordinary request: nobody supplies an instant, so the service
        samples one and every section is read as at that same one."""
        await service.dashboard(USER_ID)

        moment = mock_upcoming_dates_service.upcoming_dates.await_args.kwargs["now"]
        assert moment is not None
        assert moment.tzinfo is not None

    async def test_it_asks_for_the_dashboards_own_anchor(
        self,
        service: HomeDashboardService,
        mock_settings_repo: AsyncMock,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """The anchor is resolved once for the whole page and handed down, so
        this section cannot land on a different day from the agenda beside it.
        """
        mock_settings_repo.get_timezone.return_value = "Australia/Sydney"

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert mock_upcoming_dates_service.upcoming_dates.await_args.kwargs[
            "today"
        ] == datetime.date(2026, 7, 31)

    async def test_reading_it_costs_no_second_settings_read(
        self, service: HomeDashboardService, mock_settings_repo: AsyncMock
    ) -> None:
        """Passing the anchor down is what makes this true; asking the contacts
        service to resolve its own would be a second read of the same row."""
        await service.dashboard(USER_ID)

        mock_settings_repo.get_timezone.assert_awaited_once_with(USER_ID)

    async def test_the_window_and_the_dates_reach_the_payload(
        self,
        service: HomeDashboardService,
        mock_upcoming_dates_service: AsyncMock,
        mock_settings_repo: AsyncMock,
    ) -> None:
        window = upcoming_window(ANCHOR)
        mock_upcoming_dates_service.upcoming_dates.return_value = UpcomingContactDates(
            window=window, dates=(UPCOMING_BIRTHDAY,)
        )

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.upcoming_dates.data == UpcomingDatesSectionData(
            window=window, dates=(UPCOMING_BIRTHDAY,)
        )

    async def test_an_empty_window_is_ready_rather_than_unavailable(
        self, service: HomeDashboardService
    ) -> None:
        """ "Nothing coming up" is an answer, and a good one — it must not arrive
        looking like the section that could not answer at all."""
        dashboard = await service.dashboard(USER_ID)

        assert dashboard.upcoming_dates.status is SectionStatus.READY
        assert dashboard.upcoming_dates.data is not None
        assert dashboard.upcoming_dates.data.dates == ()

    async def test_a_failure_reading_it_leaves_the_other_three_alone(
        self, service: HomeDashboardService, mock_upcoming_dates_service: AsyncMock
    ) -> None:
        mock_upcoming_dates_service.upcoming_dates.side_effect = RuntimeError(
            "contacts query blew up"
        )

        dashboard = await service.dashboard(USER_ID)

        assert dashboard.upcoming_dates.status is SectionStatus.UNAVAILABLE
        assert dashboard.upcoming_dates.data is None
        for name in ("summary", "agenda", "tasks"):
            assert getattr(dashboard, name).status is SectionStatus.READY, name
