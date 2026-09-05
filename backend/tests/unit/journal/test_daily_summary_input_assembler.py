"""Unit tests for DailySummaryInputAssembler."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals import EventDateRange, Journal, MoodData
from core_shared.models.journals.daily_summary import JournalDailySummary

from app.core.journal.models.agenda import AgendaEntry
from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)
from app.core.journal.services.journal_date_resolver import local_day_window


def _make_journal(
    journal_id: int = 1,
    title: str = "Test Journal",
    content: str = "Test content",
    user_id: str = "user123",
) -> Journal:
    """Helper to create a test journal."""
    return Journal(
        id=journal_id,
        user_id=user_id,
        title=title,
        content=content,
        event_date_range=EventDateRange(
            start=datetime(2026, 4, 27, tzinfo=UTC),
            end=datetime(2026, 4, 27, tzinfo=UTC),
        ),
    )


@pytest.fixture
def mock_journal_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_all.return_value = []
    repo.get_types.return_value = ["NOTE"]
    return repo


@pytest.fixture
def mock_mood_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_journal_id.return_value = None
    return repo


@pytest.fixture
def mock_contact_rel_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_journal.return_value = []
    return repo


@pytest.fixture
def mock_summary_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_user_and_date.return_value = None
    return repo


@pytest.fixture
def assembler(
    mock_journal_repo: AsyncMock,
    mock_mood_repo: AsyncMock,
    mock_contact_rel_repo: AsyncMock,
    mock_summary_repo: AsyncMock,
) -> DailySummaryInputAssembler:
    return DailySummaryInputAssembler(
        journal_repo=mock_journal_repo,
        mood_repo=mock_mood_repo,
        contact_relationship_repo=mock_contact_rel_repo,
        summary_repo=mock_summary_repo,
    )


class TestDailySummaryInputAssembler:
    """Test input assembly from mocked repositories."""

    @pytest.mark.asyncio
    async def test_empty_day_returns_zero_counts(
        self, assembler: DailySummaryInputAssembler, mock_journal_repo: AsyncMock
    ) -> None:
        """An empty day returns empty input with zero counts."""
        mock_journal_repo.get_all.return_value = []

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.user_id == "user123"
        assert result.summary_date == date(2026, 4, 27)
        assert result.journal_count == 0
        assert result.event_count == 0
        assert result.journals == []
        assert result.contact_names == []
        assert result.mood_values == []
        assert result.previous_summary is None

    @pytest.mark.asyncio
    async def test_assembles_journal_entries(
        self,
        assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
    ) -> None:
        """Journals are assembled into DailySummaryJournalEntry objects."""
        j1 = _make_journal(journal_id=1, title="Morning Run", content="5km run")
        j2 = _make_journal(journal_id=2, title="Team Meeting", content="Q2 goals")
        mock_journal_repo.get_all.return_value = [j1, j2]

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.journal_count == 2
        assert len(result.journals) == 2
        assert result.journals[0].title == "Morning Run"
        assert result.journals[0].content == "5km run"
        assert result.journals[1].title == "Team Meeting"

    @pytest.mark.asyncio
    async def test_counts_events(
        self,
        assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
    ) -> None:
        """Event count is computed from journal types."""
        j1 = _make_journal(journal_id=1, title="Meeting")
        j2 = _make_journal(journal_id=2, title="Note")
        mock_journal_repo.get_all.return_value = [j1, j2]

        # First journal is EVENT, second is NOTE
        mock_journal_repo.get_types.side_effect = [
            ["EVENT", "NOTE"],
            ["NOTE"],
        ]

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.event_count == 1
        assert result.journals[0].types == ["EVENT", "NOTE"]
        assert result.journals[1].types == ["NOTE"]

    @pytest.mark.asyncio
    async def test_gathers_contact_names(
        self,
        assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
        mock_contact_rel_repo: AsyncMock,
    ) -> None:
        """Contact names are gathered from relationships."""
        j1 = _make_journal(journal_id=1, title="Meeting with Alice")
        mock_journal_repo.get_all.return_value = [j1]

        rel = MagicMock()
        rel.contact_name = "Alice Smith"
        mock_contact_rel_repo.get_by_journal.return_value = [rel]

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.contact_names == ["Alice Smith"]
        assert result.journals[0].contact_names == ["Alice Smith"]

    @pytest.mark.asyncio
    async def test_gathers_mood_data(
        self,
        assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
        mock_mood_repo: AsyncMock,
    ) -> None:
        """Mood values are gathered from mood data."""
        j1 = _make_journal(journal_id=1, title="Mood Entry")
        mock_journal_repo.get_all.return_value = [j1]

        mood = MoodData(journal_id=1, mood_value=7, energy_level=6)
        mock_mood_repo.find_by_journal_id.return_value = mood

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.mood_values == [7]
        assert result.journals[0].mood_value == 7
        assert result.journals[0].energy_level == 6

    @pytest.mark.asyncio
    async def test_mood_average_across_multiple(
        self,
        assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
        mock_mood_repo: AsyncMock,
    ) -> None:
        """Multiple mood entries contribute to mood_values list."""
        j1 = _make_journal(journal_id=1, title="Morning")
        j2 = _make_journal(journal_id=2, title="Evening")
        mock_journal_repo.get_all.return_value = [j1, j2]

        mood1 = MoodData(journal_id=1, mood_value=5, energy_level=4)
        mood2 = MoodData(journal_id=2, mood_value=9, energy_level=8)
        mock_mood_repo.find_by_journal_id.side_effect = [mood1, mood2]

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.mood_values == [5, 9]

    @pytest.mark.asyncio
    async def test_includes_previous_summary_when_generated(
        self,
        assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Previous summary text is included when one exists with GENERATED status."""
        mock_journal_repo.get_all.return_value = []
        existing = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Previous summary text.",
            status=SummaryStatus.GENERATED,
        )
        mock_summary_repo.find_by_user_and_date.return_value = existing

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.previous_summary == "Previous summary text."

    @pytest.mark.asyncio
    async def test_excludes_previous_summary_when_pending(
        self,
        assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Previous summary is not included when status is not GENERATED."""
        mock_journal_repo.get_all.return_value = []
        existing = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Stale text.",
            status=SummaryStatus.PENDING,
        )
        mock_summary_repo.find_by_user_and_date.return_value = existing

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.previous_summary is None


class TestDailySummarySeriesNames:
    """Series membership is included per entry via one bulk lookup."""

    @pytest.mark.asyncio
    async def test_assemble_includes_series_names_per_entry(
        self,
        mock_journal_repo: AsyncMock,
        mock_mood_repo: AsyncMock,
        mock_contact_rel_repo: AsyncMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Entries carry their series names; journals without series get []."""
        j1 = _make_journal(journal_id=1, title="Physio session")
        j2 = _make_journal(journal_id=2, title="One-off note")
        mock_journal_repo.get_all.return_value = [j1, j2]

        mock_series_repo = AsyncMock()
        mock_series_repo.get_series_names_for_journal_ids.return_value = {
            1: ["Physio appointments"],
        }
        assembler = DailySummaryInputAssembler(
            journal_repo=mock_journal_repo,
            mood_repo=mock_mood_repo,
            contact_relationship_repo=mock_contact_rel_repo,
            summary_repo=mock_summary_repo,
            series_repo=mock_series_repo,
        )

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.journals[0].series_names == ["Physio appointments"]
        assert result.journals[1].series_names == []
        mock_series_repo.get_series_names_for_journal_ids.assert_awaited_once_with(
            [1, 2], "user123"
        )

    @pytest.mark.asyncio
    async def test_assemble_without_series_repo_defaults_to_empty(
        self, assembler: DailySummaryInputAssembler, mock_journal_repo: AsyncMock
    ) -> None:
        """Without a series repo the entries carry no series names."""
        mock_journal_repo.get_all.return_value = [_make_journal(journal_id=1)]

        result = await assembler.assemble("user123", date(2026, 4, 27))

        assert result.journals[0].series_names == []


# Two zones far enough from UTC that one local day never shares a UTC date with
# it, so a UTC-anchored reading of "today" cannot pass these by accident.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14
FAR_WEST = "Pacific/Niue"  # UTC-11


def _agenda_entry(journal_id: int = 1, title: str = "Design review") -> AgendaEntry:
    """One agenda entry, with only the fields these tests read set."""
    start = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)
    return AgendaEntry(
        journal_id=journal_id,
        title=title,
        is_all_day=False,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )


@pytest.fixture
def mock_agenda_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_entries_in_window.return_value = []
    return repo


@pytest.fixture
def agenda_assembler(
    mock_journal_repo: AsyncMock,
    mock_mood_repo: AsyncMock,
    mock_contact_rel_repo: AsyncMock,
    mock_summary_repo: AsyncMock,
    mock_agenda_repo: AsyncMock,
) -> DailySummaryInputAssembler:
    return DailySummaryInputAssembler(
        journal_repo=mock_journal_repo,
        mood_repo=mock_mood_repo,
        contact_relationship_repo=mock_contact_rel_repo,
        summary_repo=mock_summary_repo,
        agenda_repo=mock_agenda_repo,
    )


class TestTodaysAgendaIsAssembled:
    """The current day's agenda travels with the rest of the day's input."""

    @pytest.mark.asyncio
    async def test_assembles_todays_agenda(
        self,
        agenda_assembler: DailySummaryInputAssembler,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        """Entries arrive on the input in the order the agenda draws them."""
        timed = _agenda_entry(journal_id=1, title="Design review")
        all_day = AgendaEntry(
            journal_id=2,
            title="Public holiday",
            is_all_day=True,
            starts_at=datetime(2026, 4, 27, tzinfo=UTC),
            ends_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        mock_agenda_repo.list_entries_in_window.return_value = [timed, all_day]
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        result = await agenda_assembler.assemble(
            "user123", date(2026, 4, 27), "UTC", now=now
        )

        assert [entry.title for entry in result.agenda] == [
            "Public holiday",
            "Design review",
        ]

    @pytest.mark.asyncio
    async def test_agenda_window_is_the_users_local_day(
        self,
        agenda_assembler: DailySummaryInputAssembler,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        """The window and anchor are the local day's, not a UTC day's."""
        tz = ZoneInfo(FAR_EAST)
        # 13:00 UTC on the 26th is already 03:00 on the 27th in Kiritimati.
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        await agenda_assembler.assemble("user123", date(2026, 4, 27), FAR_EAST, now=now)

        mock_agenda_repo.list_entries_in_window.assert_awaited_once_with(
            "user123",
            window=local_day_window(date(2026, 4, 27), tz),
            anchor=date(2026, 4, 27),
        )

    @pytest.mark.asyncio
    async def test_today_is_resolved_east_of_utc(
        self,
        agenda_assembler: DailySummaryInputAssembler,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        """UTC's date is still the 26th, but the user's day is the 27th."""
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        gathered = await agenda_assembler.assemble(
            "user123", date(2026, 4, 27), FAR_EAST, now=now
        )
        stale = await agenda_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_EAST, now=now
        )

        assert mock_agenda_repo.list_entries_in_window.await_count == 1
        assert gathered.summary_date == date(2026, 4, 27)
        assert stale.agenda == []

    @pytest.mark.asyncio
    async def test_today_is_resolved_west_of_utc(
        self,
        agenda_assembler: DailySummaryInputAssembler,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        """UTC has ticked over to the 27th; in Niue it is still the 26th."""
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        await agenda_assembler.assemble("user123", date(2026, 4, 27), FAR_WEST, now=now)
        assert mock_agenda_repo.list_entries_in_window.await_count == 0

        await agenda_assembler.assemble("user123", date(2026, 4, 26), FAR_WEST, now=now)
        assert mock_agenda_repo.list_entries_in_window.await_count == 1


class TestTheAgendaIsNotReadForAnyOtherDay:
    """A past-day summary describes that day, and costs no agenda round trip."""

    @pytest.mark.asyncio
    async def test_past_day_does_not_read_the_agenda(
        self,
        agenda_assembler: DailySummaryInputAssembler,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await agenda_assembler.assemble(
            "user123", date(2026, 4, 26), "UTC", now=now
        )

        assert result.agenda == []
        mock_agenda_repo.list_entries_in_window.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_future_day_does_not_read_the_agenda(
        self,
        agenda_assembler: DailySummaryInputAssembler,
        mock_agenda_repo: AsyncMock,
    ) -> None:
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await agenda_assembler.assemble(
            "user123", date(2026, 4, 28), "UTC", now=now
        )

        assert result.agenda == []
        mock_agenda_repo.list_entries_in_window.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_agenda_repo_defaults_to_empty(
        self, assembler: DailySummaryInputAssembler
    ) -> None:
        """The dependency is optional, as the series repository already is."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await assembler.assemble("user123", date(2026, 4, 27), "UTC", now=now)

        assert result.agenda == []
