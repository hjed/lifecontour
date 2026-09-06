"""Unit tests for DailySummaryInputAssembler."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals import EventDateRange, Journal, MoodData
from core_shared.models.journals.daily_summary import JournalDailySummary
from core_shared.models.tasks import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    Task,
    TaskJournalRef,
    TaskReadModel,
    UpcomingTasks,
    build_task_read_model,
    upcoming_window,
)

from app.core.journal.models.agenda import AgendaEntry
from app.core.journal.services import daily_summary_input_assembler
from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)
from app.core.journal.services.journal_date_resolver import local_day_window
from tests.unit.journal.upcoming_date_doubles import (
    coming_up,
    occurring,
    stored_date,
)

# See the note in ``test_daily_summary_prompt_builder``: this suite was outside
# CI's marker selection too.
pytestmark = pytest.mark.unit


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


def _read_model(
    task_id: int, *, due_date: date, text: str = "book the venue"
) -> TaskReadModel:
    """One assembled task, built the way the read service builds one.

    Through ``build_task_read_model`` rather than by constructing the frozen
    model directly, so ``lapse_reason`` is derived here exactly as it is in
    production — the same reasoning ``tests/unit/tasks/test_task_upcoming_window``
    gives for its own helper.
    """
    due_journal = TaskJournalRef(
        id=900 + task_id, title=f"journal {task_id}", date=due_date, cancelled=False
    )
    return build_task_read_model(
        task=Task(
            id=task_id,
            user_id="user123",
            text=text,
            creating_journal_id=1,
            due_journal_id=due_journal.id,
        ),
        creating_journal=TaskJournalRef(
            id=1, title="where it arose", date=due_date, cancelled=False
        ),
        due_journal=due_journal,
        intermediate_journals=[],
        contacts=[],
        today=due_date,
    )


def _upcoming(*models: TaskReadModel, today: date = date(2026, 4, 27)) -> UpcomingTasks:
    """The listing's answer, window and all."""
    return UpcomingTasks(
        window=upcoming_window(today, DEFAULT_UPCOMING_DAYS_AHEAD), tasks=models
    )


@pytest.fixture
def mock_task_read_service() -> AsyncMock:
    service = AsyncMock()
    service.read_models_for_upcoming_window.return_value = _upcoming()
    # Both listings default to *gathered, nothing found*, which is the shape a
    # quiet day really has. Left unset, an ``AsyncMock`` would hand back another
    # mock, and a test asserting "nothing was due" would pass against anything.
    service.read_models_due_in_journals.return_value = []
    return service


@pytest.fixture
def tasks_assembler(
    mock_journal_repo: AsyncMock,
    mock_mood_repo: AsyncMock,
    mock_contact_rel_repo: AsyncMock,
    mock_summary_repo: AsyncMock,
    mock_agenda_repo: AsyncMock,
    mock_task_read_service: AsyncMock,
) -> DailySummaryInputAssembler:
    return DailySummaryInputAssembler(
        journal_repo=mock_journal_repo,
        mood_repo=mock_mood_repo,
        contact_relationship_repo=mock_contact_rel_repo,
        summary_repo=mock_summary_repo,
        agenda_repo=mock_agenda_repo,
        task_read_service=mock_task_read_service,
    )


class TestTheUpcomingWindowIsAssembled:
    """The week's commitments travel with the current day's input."""

    @pytest.mark.asyncio
    async def test_assembles_the_upcoming_window(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """The listing's answer arrives whole — its order and its window."""
        soonest = _read_model(1, due_date=date(2026, 4, 27), text="book the venue")
        later = _read_model(2, due_date=date(2026, 4, 30), text="confirm the flights")
        mock_task_read_service.read_models_for_upcoming_window.return_value = _upcoming(
            soonest, later
        )
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 27), "UTC", now=now
        )

        assert result.upcoming_tasks is not None
        assert [model.task.text for model in result.upcoming_tasks.tasks] == [
            "book the venue",
            "confirm the flights",
        ]
        assert result.upcoming_tasks.window.first_day == date(2026, 4, 27)
        assert result.upcoming_tasks.window.last_day == date(2026, 5, 4)

    @pytest.mark.asyncio
    async def test_asks_for_the_specifications_window_at_the_assemblys_instant(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """Seven days ahead, anchored on the instant the rest of the day used.

        The instant is handed over rather than left to the read service's own
        clock: with ``now=None`` each reading samples afresh, and a request
        crossing local midnight between them would gather a window for one day
        while the prompt labels the input another.
        """
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        await tasks_assembler.assemble("user123", date(2026, 4, 27), "UTC", now=now)

        mock_task_read_service.read_models_for_upcoming_window.assert_awaited_once_with(
            "user123",
            days_ahead=DEFAULT_UPCOMING_DAYS_AHEAD,
            now=now,
            timezone=ZoneInfo("UTC"),
        )

    @pytest.mark.asyncio
    async def test_today_is_resolved_east_of_utc(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """UTC's date is still the 26th, but the user's day is the 27th."""
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        gathered = await tasks_assembler.assemble(
            "user123", date(2026, 4, 27), FAR_EAST, now=now
        )
        stale = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_EAST, now=now
        )

        assert gathered.upcoming_tasks is not None
        assert stale.upcoming_tasks is None
        assert mock_task_read_service.read_models_for_upcoming_window.await_count == 1

    @pytest.mark.asyncio
    async def test_today_is_resolved_west_of_utc(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """UTC has ticked over to the 27th; in Niue it is still the 26th."""
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        ahead = await tasks_assembler.assemble(
            "user123", date(2026, 4, 27), FAR_WEST, now=now
        )
        assert ahead.upcoming_tasks is None

        gathered = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_WEST, now=now
        )
        assert gathered.upcoming_tasks is not None
        assert mock_task_read_service.read_models_for_upcoming_window.await_count == 1

    @pytest.mark.asyncio
    async def test_nothing_due_is_not_the_same_as_nothing_gathered(
        self,
        tasks_assembler: DailySummaryInputAssembler,
    ) -> None:
        """An empty week is a fact about it; a past day was never asked."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 27), "UTC", now=now
        )

        assert result.upcoming_tasks is not None
        assert result.upcoming_tasks.tasks == ()


class TestTasksAreNotReadForAnyOtherDay:
    """Forward-looking material is the current day's, and costs nothing else."""

    @pytest.mark.asyncio
    async def test_past_day_does_not_read_tasks(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), "UTC", now=now
        )

        assert result.upcoming_tasks is None
        mock_task_read_service.read_models_for_upcoming_window.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_future_day_does_not_read_tasks(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 28), "UTC", now=now
        )

        assert result.upcoming_tasks is None
        mock_task_read_service.read_models_for_upcoming_window.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_the_read_service_defaults_to_nothing_gathered(
        self, assembler: DailySummaryInputAssembler
    ) -> None:
        """The dependency is optional, as the agenda port already is."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await assembler.assemble("user123", date(2026, 4, 27), "UTC", now=now)

        assert result.upcoming_tasks is None


class TestOneClockReadingPerAssembly:
    """Every day-based decision in one assembly reads one instant."""

    @pytest.mark.asyncio
    async def test_the_clock_is_read_once_and_handed_on(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A caller without an instant still gives every collaborator one.

        Left to themselves the agenda guard, the tasks guard and the read
        service would each sample the wall clock, and an assembly crossing local
        midnight between two of them would gather a window for a day the rest of
        the input is not about.
        """
        instant = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)
        readings = 0

        def _counting_clock() -> datetime:
            nonlocal readings
            readings += 1
            return instant

        monkeypatch.setattr(daily_summary_input_assembler, "_utc_now", _counting_clock)

        await tasks_assembler.assemble("user123", date(2026, 4, 27), "UTC")

        assert readings == 1
        mock_task_read_service.read_models_for_upcoming_window.assert_awaited_once_with(
            "user123",
            days_ahead=DEFAULT_UPCOMING_DAYS_AHEAD,
            now=instant,
            timezone=ZoneInfo("UTC"),
        )


class TestOneTimezoneReadingPerAssembly:
    """The zone travels down with the instant, for the same reason."""

    @pytest.mark.asyncio
    async def test_the_resolved_zone_is_handed_to_the_read_service(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """Left to itself the read service would read ``user_settings`` again.

        Two reads in one request are two statements under READ COMMITTED, so a
        timezone changed between them gives a prompt labelled today in the old
        zone around a window built in the new one. Handing the zone down is what
        makes the two agree structurally rather than by timing.
        """
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        await tasks_assembler.assemble("user123", date(2026, 4, 27), FAR_EAST, now=now)

        kwargs = (
            mock_task_read_service.read_models_for_upcoming_window.await_args.kwargs
        )
        assert kwargs["timezone"] == ZoneInfo(FAR_EAST)

    @pytest.mark.asyncio
    async def test_the_zone_handed_down_is_the_one_the_day_was_judged_in(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """The guard and the read cannot be told apart by the zone they used.

        Asserted at the boundary that separates them: 13:00Z is the 26th in UTC
        and already the 27th in Kiritimati, so the guard only fires for the 27th
        if it judged the day in the user's zone — and the read is only reached
        at all when it does.
        """
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        gathered = await tasks_assembler.assemble(
            "user123", date(2026, 4, 27), FAR_EAST, now=now
        )

        assert gathered.upcoming_tasks is not None
        kwargs = (
            mock_task_read_service.read_models_for_upcoming_window.await_args.kwargs
        )
        assert kwargs["timezone"] == ZoneInfo(FAR_EAST)
        assert kwargs["now"] == now


class TestThePastDaysTasksAreAssembled:
    """What was due on a day that has been and gone, and how it stands now."""

    @pytest.mark.asyncio
    async def test_assembles_the_days_commitments(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """The listing's answer arrives whole, in the order it came back."""
        first = _read_model(1, due_date=date(2026, 4, 26), text="book the venue")
        second = _read_model(2, due_date=date(2026, 4, 26), text="call the council")
        mock_task_read_service.read_models_due_in_journals.return_value = [
            first,
            second,
        ]
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), "UTC", now=now
        )

        assert result.past_day_tasks is not None
        assert [model.task.text for model in result.past_day_tasks] == [
            "book the venue",
            "call the council",
        ]

    @pytest.mark.asyncio
    async def test_asks_about_exactly_the_days_journals(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_journal_repo: AsyncMock,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """The journals already fetched, not a second window over the same day.

        The day's journals were selected by *overlap*, so a multi-day journal
        running through the day is one of them. Re-deriving the span inside the
        tasks read would answer for a quietly different set than the one the
        prompt is describing.
        """
        mock_journal_repo.get_all.return_value = [
            _make_journal(journal_id=11),
            _make_journal(journal_id=12),
        ]
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        await tasks_assembler.assemble("user123", date(2026, 4, 26), "UTC", now=now)

        mock_task_read_service.read_models_due_in_journals.assert_awaited_once_with(
            "user123",
            [11, 12],
            now=now,
            timezone=ZoneInfo("UTC"),
        )

    @pytest.mark.asyncio
    async def test_nothing_due_is_not_the_same_as_nothing_gathered(
        self, tasks_assembler: DailySummaryInputAssembler
    ) -> None:
        """An empty day is a fact about it; a current day was never asked.

        The same distinction the week's window keeps, and load-bearing for the
        same reason: only one of the two is something the prompt can say.
        """
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), "UTC", now=now
        )

        assert result.past_day_tasks == []

    @pytest.mark.asyncio
    async def test_today_is_resolved_east_of_utc(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """UTC's date is still the 26th, but the user's day is already the 27th.

        So *their* 26th is a past day and their 27th is today — the opposite of
        what a UTC-anchored guard would decide about both.
        """
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        past = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_EAST, now=now
        )
        current = await tasks_assembler.assemble(
            "user123", date(2026, 4, 27), FAR_EAST, now=now
        )

        assert past.past_day_tasks is not None
        assert current.past_day_tasks is None
        assert mock_task_read_service.read_models_due_in_journals.await_count == 1

    @pytest.mark.asyncio
    async def test_today_is_resolved_west_of_utc(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """UTC has ticked over to the 27th; in Niue it is still the 26th."""
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        current = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_WEST, now=now
        )
        assert current.past_day_tasks is None

        past = await tasks_assembler.assemble(
            "user123", date(2026, 4, 25), FAR_WEST, now=now
        )
        assert past.past_day_tasks is not None
        assert mock_task_read_service.read_models_due_in_journals.await_count == 1


class TestPastDayTasksAreNotReadForAnyOtherDay:
    """A resolution is a past day's, and the two guards are separate rules."""

    @pytest.mark.asyncio
    async def test_the_current_day_does_not_read_them(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """Today's commitments are the week's window, and listing them twice
        would put the same task in two sections of one prompt."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 27), "UTC", now=now
        )

        assert result.past_day_tasks is None
        mock_task_read_service.read_models_due_in_journals.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_future_day_does_not_read_them(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """Nothing has resolved on a day that has not happened."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await tasks_assembler.assemble(
            "user123", date(2026, 4, 28), "UTC", now=now
        )

        assert result.past_day_tasks is None
        mock_task_read_service.read_models_due_in_journals.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_the_read_service_defaults_to_nothing_gathered(
        self, assembler: DailySummaryInputAssembler
    ) -> None:
        """The dependency is optional, as the agenda port and the window are."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await assembler.assemble("user123", date(2026, 4, 26), "UTC", now=now)

        assert result.past_day_tasks is None


class TestOnePastDayReadingPerAssembly:
    """A past day's read takes the same instant and zone every other one does."""

    @pytest.mark.asyncio
    async def test_the_clock_is_read_once_for_a_past_day_too(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Three guards now hang off one reading rather than two.

        The past-day guard is the third question this assembly asks about which
        day it is, and a third independent sampling of the wall clock is a third
        chance for one assembly to straddle local midnight.
        """
        instant = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)
        readings = 0

        def _counting_clock() -> datetime:
            nonlocal readings
            readings += 1
            return instant

        monkeypatch.setattr(daily_summary_input_assembler, "_utc_now", _counting_clock)

        await tasks_assembler.assemble("user123", date(2026, 4, 26), "UTC")

        assert readings == 1
        kwargs = mock_task_read_service.read_models_due_in_journals.await_args.kwargs
        assert kwargs["now"] == instant

    @pytest.mark.asyncio
    async def test_the_zone_handed_down_is_the_one_the_day_was_judged_in(
        self,
        tasks_assembler: DailySummaryInputAssembler,
        mock_task_read_service: AsyncMock,
    ) -> None:
        """The guard and the read cannot be told apart by the zone they used.

        Asserted at the boundary that separates them: 13:00Z is the 26th in UTC
        and already the 27th in Kiritimati, so the 26th is only a *past* day if
        the guard judged it in the user's zone — and the read is only reached
        when it does.
        """
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        gathered = await tasks_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_EAST, now=now
        )

        assert gathered.past_day_tasks is not None
        kwargs = mock_task_read_service.read_models_due_in_journals.await_args.kwargs
        assert kwargs["timezone"] == ZoneInfo(FAR_EAST)
        assert kwargs["now"] == now


@pytest.fixture
def mock_upcoming_dates_service() -> AsyncMock:
    service = AsyncMock()
    # *Gathered, nothing coming up* — the shape a quiet week really has. Left
    # unset an ``AsyncMock`` hands back another mock, and a test asserting the
    # week was empty would pass against anything.
    service.upcoming_dates.return_value = coming_up()
    return service


@pytest.fixture
def dates_assembler(
    mock_journal_repo: AsyncMock,
    mock_mood_repo: AsyncMock,
    mock_contact_rel_repo: AsyncMock,
    mock_summary_repo: AsyncMock,
    mock_agenda_repo: AsyncMock,
    mock_task_read_service: AsyncMock,
    mock_upcoming_dates_service: AsyncMock,
) -> DailySummaryInputAssembler:
    """Every collaborator, so the fourth guard is exercised beside the other three."""
    return DailySummaryInputAssembler(
        journal_repo=mock_journal_repo,
        mood_repo=mock_mood_repo,
        contact_relationship_repo=mock_contact_rel_repo,
        summary_repo=mock_summary_repo,
        agenda_repo=mock_agenda_repo,
        task_read_service=mock_task_read_service,
        upcoming_dates_service=mock_upcoming_dates_service,
    )


class TestTheUpcomingDatesAreAssembled:
    """Whose dates are coming up travels with the current day's input."""

    @pytest.mark.asyncio
    async def test_assembles_the_weeks_dates(
        self,
        dates_assembler: DailySummaryInputAssembler,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """The read's answer arrives whole — its order and its window."""
        mock_upcoming_dates_service.upcoming_dates.return_value = coming_up(
            occurring(stored_date(1, month=4, day=28), name="First Person"),
            occurring(stored_date(2, month=5, day=1), name="Second Person"),
        )
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        result = await dates_assembler.assemble(
            "user123", date(2026, 4, 27), "UTC", now=now
        )

        assert result.upcoming_dates is not None
        assert [
            entry.contact.display_name for entry in result.upcoming_dates.dates
        ] == [
            "First Person",
            "Second Person",
        ]
        assert result.upcoming_dates.window.first_day == date(2026, 4, 27)
        assert result.upcoming_dates.window.last_day == date(2026, 5, 4)

    @pytest.mark.asyncio
    async def test_asks_for_seven_days_at_the_assemblys_own_day_and_instant(
        self,
        dates_assembler: DailySummaryInputAssembler,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """Both halves of the question travel, and each buys something.

        ``today`` pins the day **and** skips the service's own
        ``user_settings`` read — this assembly has already read that row to
        decide which day it is summarising, and a second statement under READ
        COMMITTED can see a timezone change the first did not. ``now`` pins the
        instant the importance signals measure their thirty-day recency back
        from, which is the other half the signature asks for.
        """
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        await dates_assembler.assemble("user123", date(2026, 4, 27), "UTC", now=now)

        mock_upcoming_dates_service.upcoming_dates.assert_awaited_once_with(
            "user123",
            days_ahead=DEFAULT_UPCOMING_DAYS_AHEAD,
            today=date(2026, 4, 27),
            now=now,
        )

    @pytest.mark.asyncio
    async def test_today_is_resolved_east_of_utc(
        self,
        dates_assembler: DailySummaryInputAssembler,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """UTC's date is still the 26th, but the user's day is the 27th."""
        now = datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

        gathered = await dates_assembler.assemble(
            "user123", date(2026, 4, 27), FAR_EAST, now=now
        )
        stale = await dates_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_EAST, now=now
        )

        assert gathered.upcoming_dates is not None
        assert stale.upcoming_dates is None
        assert mock_upcoming_dates_service.upcoming_dates.await_count == 1
        assert mock_upcoming_dates_service.upcoming_dates.await_args.kwargs[
            "today"
        ] == date(2026, 4, 27)

    @pytest.mark.asyncio
    async def test_today_is_resolved_west_of_utc(
        self,
        dates_assembler: DailySummaryInputAssembler,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        """UTC has ticked over to the 27th; in Niue it is still the 26th."""
        now = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)

        ahead = await dates_assembler.assemble(
            "user123", date(2026, 4, 27), FAR_WEST, now=now
        )
        assert ahead.upcoming_dates is None

        gathered = await dates_assembler.assemble(
            "user123", date(2026, 4, 26), FAR_WEST, now=now
        )
        assert gathered.upcoming_dates is not None
        assert mock_upcoming_dates_service.upcoming_dates.await_count == 1
        assert mock_upcoming_dates_service.upcoming_dates.await_args.kwargs[
            "today"
        ] == date(2026, 4, 26)

    @pytest.mark.asyncio
    async def test_a_quiet_week_is_not_the_same_as_nothing_gathered(
        self, dates_assembler: DailySummaryInputAssembler
    ) -> None:
        """An empty week is a fact about it; a past day was never asked."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await dates_assembler.assemble(
            "user123", date(2026, 4, 27), "UTC", now=now
        )

        assert result.upcoming_dates is not None
        assert result.upcoming_dates.dates == ()


class TestDatesAreNotReadForAnyOtherDay:
    """Forward-looking material is the current day's, and costs nothing else."""

    @pytest.mark.asyncio
    async def test_past_day_does_not_read_dates(
        self,
        dates_assembler: DailySummaryInputAssembler,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await dates_assembler.assemble(
            "user123", date(2026, 4, 26), "UTC", now=now
        )

        assert result.upcoming_dates is None
        mock_upcoming_dates_service.upcoming_dates.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_future_day_does_not_read_dates(
        self,
        dates_assembler: DailySummaryInputAssembler,
        mock_upcoming_dates_service: AsyncMock,
    ) -> None:
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await dates_assembler.assemble(
            "user123", date(2026, 4, 28), "UTC", now=now
        )

        assert result.upcoming_dates is None
        mock_upcoming_dates_service.upcoming_dates.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_the_service_defaults_to_nothing_gathered(
        self, assembler: DailySummaryInputAssembler
    ) -> None:
        """The dependency is optional, as the agenda port and read service are."""
        now = datetime(2026, 4, 27, 9, 0, tzinfo=UTC)

        result = await assembler.assemble("user123", date(2026, 4, 27), "UTC", now=now)

        assert result.upcoming_dates is None


class TestOneClockReadingWithFourGuards:
    """The fourth day question hangs off the same single reading as the others."""

    @pytest.mark.asyncio
    async def test_the_clock_is_still_read_once(
        self,
        dates_assembler: DailySummaryInputAssembler,
        mock_upcoming_dates_service: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Adding a guard must not add a reading.

        Each collaborator left to itself samples the wall clock afresh, and an
        assembly crossing local midnight between two of them gathers a week for
        one day while the rest of the input describes another.
        """
        instant = datetime(2026, 4, 27, 3, 0, tzinfo=UTC)
        readings = 0

        def _counting_clock() -> datetime:
            nonlocal readings
            readings += 1
            return instant

        monkeypatch.setattr(daily_summary_input_assembler, "_utc_now", _counting_clock)

        await dates_assembler.assemble("user123", date(2026, 4, 27), "UTC")

        assert readings == 1
        mock_upcoming_dates_service.upcoming_dates.assert_awaited_once_with(
            "user123",
            days_ahead=DEFAULT_UPCOMING_DAYS_AHEAD,
            today=date(2026, 4, 27),
            now=instant,
        )
