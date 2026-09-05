"""Unit tests for the upcoming-dates service: everything the pure rule cannot see.

The rule is tested in ``test_upcoming_dates_rule.py``. What is left over is the
service's own job, and all of it is about *how many times* something happens and
*whose day* it happens on:

- the pairs the query is actually handed, which is the only thing standing
  between the recurrence rule and a query that fetches everything;
- **one clock read per request**, structurally rather than by hoping. ITER18-001
  Phase 14 shipped a listing that read the clock twice and could therefore build
  its window against one day and judge its rows against the next, dropping a task
  from a window that claimed to include it. It shipped that bug, had it found in
  review, and then shipped a second instance of the same shape in the same file;
- **one settings read**, since a request that resolved the timezone twice could
  straddle a change to it;
- the round trips, because an N+1 here would be a page load per contact.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.contacts.entities import ImportantDate
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

from app.core.contacts.models.importance import ContactImportance
from app.core.contacts.models.repositories import (
    ContactImportanceRepository,
    UpcomingImportantDateRepository,
)
from app.core.contacts.models.upcoming_dates import (
    ContactImportantDate,
    UpcomingDateContact,
)
from app.core.contacts.services.upcoming_important_dates_service import (
    UpcomingImportantDatesService,
)
from app.core.journal.services.journal_date_resolver import JournalDateResolver

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

USER_ID = "user1"
TODAY = datetime.date(2026, 8, 11)

#: 00:30 on 12 August in Kiritimati (+14) while UTC is still on the 11th — the
#: instant that tells a local reading of "today" apart from a UTC one.
JUST_PAST_KIRITIMATI_MIDNIGHT = datetime.datetime(
    2026, 8, 11, 10, 30, tzinfo=datetime.UTC
)


class RecordingCandidates(UpcomingImportantDateRepository):
    """A candidate read that remembers what it was asked for."""

    def __init__(self, rows: list[ContactImportantDate] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[tuple[int, int], ...]] = []

    async def candidates_for(
        self, month_days: Sequence[tuple[int, int]]
    ) -> list[ContactImportantDate]:
        self.calls.append(tuple(month_days))
        return list(self.rows)


class RecordingImportance(ContactImportanceRepository):
    """A signals read that remembers which contacts it was asked about."""

    def __init__(self, signals: dict[int, ContactImportance] | None = None) -> None:
        self.signals = signals or {}
        self.calls: list[tuple[int, ...]] = []

    async def for_contacts(
        self, contact_ids: Sequence[int], *, now: datetime.datetime | None = None
    ) -> dict[int, ContactImportance]:
        self.calls.append(tuple(contact_ids))
        return {
            contact_id: self.signals[contact_id]
            for contact_id in contact_ids
            if contact_id in self.signals
        }


def candidate(
    date_id: int, contact_id: int, month: int, day: int
) -> ContactImportantDate:
    """A row as the candidate query returns one."""
    return ContactImportantDate(
        important_date=ImportantDate(
            id=date_id,
            contact_id=contact_id,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.DAY_MONTH,
            month=month,
            day=day,
        ),
        contact=UpcomingDateContact(
            id=contact_id, display_name="Ada Lovelace", photo_url=None
        ),
    )


def signals(contact_id: int) -> ContactImportance:
    """A contact nobody has touched."""
    return ContactImportance(
        contact_id=contact_id,
        is_favourite=False,
        journal_count_30d=0,
        activity_count_30d=0,
        last_activity_at=None,
    )


@pytest.fixture
def settings_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def date_resolver(settings_repo: AsyncMock) -> JournalDateResolver:
    """The real resolver over a stubbed settings row.

    Real rather than mocked so the timezone rules under test are the ones that
    run in production, not a second copy of them.
    """
    return JournalDateResolver(user_settings_repo=settings_repo)


@pytest.fixture
def candidates() -> RecordingCandidates:
    return RecordingCandidates()


@pytest.fixture
def importance() -> RecordingImportance:
    return RecordingImportance()


@pytest.fixture
def service(
    date_resolver: JournalDateResolver,
    candidates: RecordingCandidates,
    importance: RecordingImportance,
) -> UpcomingImportantDatesService:
    return UpcomingImportantDatesService(
        date_resolver=date_resolver,
        candidate_repo=candidates,
        importance_repo=importance,
    )


class TestWhatTheQueryIsAskedFor:
    """The pairs are the whole filter, so they are asserted directly."""

    async def test_it_asks_for_every_day_of_the_window(
        self, service: UpcomingImportantDatesService, candidates: RecordingCandidates
    ) -> None:
        await service.upcoming_dates(USER_ID, today=TODAY)

        assert candidates.calls == [
            ((8, 11), (8, 12), (8, 13), (8, 14), (8, 15), (8, 16), (8, 17), (8, 18))
        ]

    async def test_a_shorter_window_asks_for_fewer_days(
        self, service: UpcomingImportantDatesService, candidates: RecordingCandidates
    ) -> None:
        await service.upcoming_dates(USER_ID, today=TODAY, days_ahead=1)

        assert candidates.calls == [((8, 11), (8, 12))]

    async def test_a_window_over_a_common_years_28_february_asks_for_the_29th(
        self, service: UpcomingImportantDatesService, candidates: RecordingCandidates
    ) -> None:
        await service.upcoming_dates(
            USER_ID, today=datetime.date(2027, 2, 27), days_ahead=1
        )

        assert candidates.calls == [((2, 27), (2, 28), (2, 29))]


class TestWhoseDayItIs:
    """The window is anchored on the user's today, never on UTC's."""

    async def test_it_resolves_today_in_the_users_timezone(
        self,
        service: UpcomingImportantDatesService,
        settings_repo: AsyncMock,
        candidates: RecordingCandidates,
    ) -> None:
        """Kiritimati is a day ahead of UTC at this instant, and gets its own day."""
        settings_repo.get_timezone.return_value = "Pacific/Kiritimati"

        result = await service.upcoming_dates(
            USER_ID, now=JUST_PAST_KIRITIMATI_MIDNIGHT
        )

        assert result.window.first_day == datetime.date(2026, 8, 12)
        assert candidates.calls[0][0] == (8, 12)

    async def test_the_same_instant_read_as_utc_would_be_the_day_before(
        self, service: UpcomingImportantDatesService
    ) -> None:
        """The control for the test above: the fixture zone is UTC, and at this
        instant UTC is still on the 11th."""
        result = await service.upcoming_dates(
            USER_ID, now=JUST_PAST_KIRITIMATI_MIDNIGHT
        )

        assert result.window.first_day == datetime.date(2026, 8, 11)

    async def test_a_supplied_today_is_used_and_no_clock_is_read(
        self, service: UpcomingImportantDatesService, settings_repo: AsyncMock
    ) -> None:
        """The dashboard resolves the anchor once for all four sections and hands
        it down, so this path must not resolve a second one."""
        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert result.window.first_day == TODAY
        settings_repo.get_timezone.assert_not_awaited()

    async def test_the_timezone_is_read_once_when_it_has_to_be_read(
        self, service: UpcomingImportantDatesService, settings_repo: AsyncMock
    ) -> None:
        """A request resolving it twice could straddle a change to it."""
        await service.upcoming_dates(USER_ID, now=JUST_PAST_KIRITIMATI_MIDNIGHT)

        assert settings_repo.get_timezone.await_count == 1


class TestTheRoundTrips:
    """Two reads, whatever the window holds."""

    async def test_a_window_of_dates_costs_two_reads(
        self,
        service: UpcomingImportantDatesService,
        candidates: RecordingCandidates,
        importance: RecordingImportance,
    ) -> None:
        candidates.rows = [
            candidate(index, index, 8, 12 + index % 6) for index in range(1, 7)
        ]
        importance.signals = {index: signals(index) for index in range(1, 7)}

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert len(result.dates) == 6
        assert len(candidates.calls) == 1
        assert len(importance.calls) == 1

    async def test_the_signals_are_asked_for_once_for_every_contact_at_once(
        self,
        service: UpcomingImportantDatesService,
        candidates: RecordingCandidates,
        importance: RecordingImportance,
    ) -> None:
        candidates.rows = [candidate(1, 10, 8, 12), candidate(2, 11, 8, 13)]

        await service.upcoming_dates(USER_ID, today=TODAY)

        assert importance.calls == [(10, 11)]

    async def test_one_contact_with_two_dates_is_asked_about_once(
        self,
        service: UpcomingImportantDatesService,
        candidates: RecordingCandidates,
        importance: RecordingImportance,
    ) -> None:
        candidates.rows = [candidate(1, 10, 8, 12), candidate(2, 10, 8, 13)]

        await service.upcoming_dates(USER_ID, today=TODAY)

        assert importance.calls == [(10,)]

    async def test_an_empty_window_asks_about_no_contacts(
        self,
        service: UpcomingImportantDatesService,
        importance: RecordingImportance,
    ) -> None:
        """A quiet week is the common case and must not cost a second query.

        The service asks with an empty batch rather than branching around the
        call, and ``for_contacts`` answers an empty batch without a round trip —
        asserted on the repository itself, and again as a statement count in the
        integration suite. Branching here as well would be a second rule that
        had to agree with that one.
        """
        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert result.dates == ()
        assert importance.calls == [()]

    async def test_the_batch_is_keyed_off_the_candidates_in_one_pass(
        self,
        service: UpcomingImportantDatesService,
        candidates: RecordingCandidates,
        importance: RecordingImportance,
    ) -> None:
        """Asking about the candidates rather than the survivors keeps the
        recurrence rule to a single pass, and the two sets are the same set: a
        row only becomes a candidate by matching a day the window covers.
        """
        candidates.rows = [candidate(1, 10, 8, 12), candidate(2, 11, 8, 13)]

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert importance.calls == [(10, 11)]
        assert [date.contact.id for date in result.dates] == [10, 11]


class TestTheAnswer:
    """What the service hands back, beyond the ordering the rule owns."""

    async def test_the_window_travels_with_the_dates(
        self, service: UpcomingImportantDatesService
    ) -> None:
        result = await service.upcoming_dates(USER_ID, today=TODAY, days_ahead=3)

        assert result.window.first_day == TODAY
        assert result.window.last_day == datetime.date(2026, 8, 14)
        assert result.window.days_ahead == 3

    async def test_the_total_is_the_whole_window(
        self,
        service: UpcomingImportantDatesService,
        candidates: RecordingCandidates,
        importance: RecordingImportance,
    ) -> None:
        """The card caps at three from this payload; the service caps nothing."""
        candidates.rows = [
            candidate(index, index, 8, 11 + index % 8) for index in range(1, 13)
        ]
        importance.signals = {index: signals(index) for index in range(1, 13)}

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert result.total == 12


class TestTheBound:
    """Refused in the domain, before any read runs."""

    async def test_a_window_past_the_maximum_is_refused(
        self, service: UpcomingImportantDatesService
    ) -> None:
        with pytest.raises(ContactValidationError):
            await service.upcoming_dates(USER_ID, today=TODAY, days_ahead=91)

    async def test_a_negative_window_is_refused(
        self, service: UpcomingImportantDatesService
    ) -> None:
        with pytest.raises(ContactValidationError):
            await service.upcoming_dates(USER_ID, today=TODAY, days_ahead=-1)

    async def test_a_refused_window_costs_no_read(
        self,
        service: UpcomingImportantDatesService,
        candidates: RecordingCandidates,
        importance: RecordingImportance,
    ) -> None:
        """Only the *listing* reads are provable here: resolving the anchor can
        precede the bound check, because the window cannot be built without it."""
        with pytest.raises(ContactValidationError):
            await service.upcoming_dates(USER_ID, today=TODAY, days_ahead=91)

        assert candidates.calls == []
        assert importance.calls == []


def test_the_zone_fixture_is_a_real_zone() -> None:
    """Guards the two Kiritimati tests: a missing tzdata would make them vacuous."""
    assert ZoneInfo("Pacific/Kiritimati").utcoffset(
        datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
    ) == datetime.timedelta(hours=14)
