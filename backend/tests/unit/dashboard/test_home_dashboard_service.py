"""Unit tests for HomeDashboardService.

Pins the three rules the later phases build on: the payload declares all four
sections whether or not they have anything in them, "today" is the user's local
date and never UTC's, and one section failing costs only that section — the
others still answer, and its SAVEPOINT is rolled back so the shared connection
survives to serve them.
"""

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dashboard.models.sections import (
    AgendaSectionData,
    HomeDashboard,
    SectionStatus,
)
from app.core.dashboard.services.home_dashboard_service import HomeDashboardService
from app.core.journal.services.journal_date_resolver import JournalDateResolver

pytestmark = pytest.mark.unit

USER_ID = "test-user-123"
SECTIONS = ("summary", "agenda", "tasks", "upcoming_dates")

# 00:30 on 31 July in Sydney (+10), while UTC is still on the 30th — the instant
# that tells a local reading apart from a UTC one.
JUST_PAST_SYDNEY_MIDNIGHT = datetime.datetime(2026, 7, 30, 14, 30, tzinfo=datetime.UTC)


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


@pytest.fixture
def service(
    date_resolver: JournalDateResolver, connection: MagicMock
) -> HomeDashboardService:
    return HomeDashboardService(date_resolver=date_resolver, connection=connection)


def sections_of(dashboard: HomeDashboard) -> dict[str, Any]:
    return {name: getattr(dashboard, name) for name in SECTIONS}


class TestTheFourSectionEnvelope:
    async def test_declares_every_section_even_with_nothing_to_show(
        self, service: HomeDashboardService
    ) -> None:
        """Later phases fill this contract; none of them adds a section to it."""
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
        self, date_resolver: JournalDateResolver
    ) -> None:
        """``savepoint(None)`` no-ops, so the guard is still the guard."""
        service = HomeDashboardService(date_resolver=date_resolver, connection=None)

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
            return AgendaSectionData()

        monkeypatch.setattr(service, "_load_agenda", record)

        await service.dashboard(USER_ID, now=JUST_PAST_SYDNEY_MIDNIGHT)

        assert seen == [
            (USER_ID, datetime.date(2026, 7, 31), ZoneInfo("Australia/Sydney"))
        ]
