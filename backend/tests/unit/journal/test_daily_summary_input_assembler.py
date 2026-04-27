"""Unit tests for DailySummaryInputAssembler."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals import EventDateRange, Journal, MoodData
from core_shared.models.journals.daily_summary import JournalDailySummary

from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)


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
