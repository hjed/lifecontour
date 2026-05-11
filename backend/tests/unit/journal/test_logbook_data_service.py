"""Unit tests for LogbookDataService hierarchy assembly."""

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import (
    EventDateRange,
    LogbookEntryData,
    LogbookSummaryCalculator,
    ParticipantIndexCalculator,
)

from app.core.journal.services.logbook_data_service import LogbookDataService


def _make_entry(
    entry_id: int,
    parent_id: int | None = None,
    title: str = "Test",
    types: list[str] | None = None,
) -> LogbookEntryData:
    """Create a minimal LogbookEntryData for testing."""
    return LogbookEntryData(
        id=entry_id,
        title=title,
        content="",
        event_date_range=EventDateRange(
            start=datetime.datetime(2024, 1, entry_id % 28 + 1, tzinfo=datetime.UTC),
            end=datetime.datetime(2024, 1, entry_id % 28 + 1, tzinfo=datetime.UTC),
        ),
        parent_id=parent_id,
        journal_types=types or ["BUSHWALKING"],
    )


def _make_service(raw_entries: list[LogbookEntryData]) -> LogbookDataService:
    """Create a LogbookDataService with a mock repository returning the given entries."""
    repo = AsyncMock()
    repo.get_logbook_entries = AsyncMock(return_value=raw_entries)
    return LogbookDataService(
        repository=repo,
        summary_calculator=LogbookSummaryCalculator(),
        participant_calculator=ParticipantIndexCalculator(),
    )


@pytest.mark.unit
class TestLogbookDataServiceHierarchy:
    """Tests for the hierarchy assembly in LogbookDataService.get_logbook_data."""

    @pytest.mark.asyncio
    async def test_flat_entries_become_roots(self) -> None:
        """Entries with no parent_id should all become root entries."""
        entries = [_make_entry(1), _make_entry(2), _make_entry(3)]
        service = _make_service(entries)

        result = await service.get_logbook_data(user_id="u1")
        assert len(result.entries) == 3
        for e in result.entries:
            assert len(e.children) == 0

    @pytest.mark.asyncio
    async def test_parent_child_hierarchy(self) -> None:
        """Entries with parent_id should be nested under their parent."""
        parent = _make_entry(1)
        child = _make_entry(2, parent_id=1)
        entries = [parent, child]
        service = _make_service(entries)

        result = await service.get_logbook_data(user_id="u1")
        assert len(result.entries) == 1  # Only root
        root = result.entries[0]
        assert root.id == 1
        assert len(root.children) == 1
        assert root.children[0].id == 2

    @pytest.mark.asyncio
    async def test_cycle_detection_direct(self) -> None:
        """A direct cycle (A -> B -> A) should be detected and broken."""
        # A claims parent is B, B claims parent is A
        a = _make_entry(1, parent_id=2)
        b = _make_entry(2, parent_id=1)
        entries = [a, b]
        service = _make_service(entries)

        result = await service.get_logbook_data(user_id="u1")
        # Both should become roots because the cycle is broken
        # Entry 1: parent_id=2, entry 2 exists. Walk: visited={1}, check 2, add 2,
        #   then entry 2's parent is 1, which is in visited -> cycle.
        #   So entry 1 becomes root.
        # Entry 2: parent_id=1, entry 1 exists. Walk: visited={2}, check 1, add 1,
        #   then entry 1's parent is 2, which is in visited -> cycle.
        #   So entry 2 also becomes root.
        assert len(result.entries) == 2

    @pytest.mark.asyncio
    async def test_cycle_detection_indirect(self) -> None:
        """An indirect cycle (A -> B -> C -> A) should be detected."""
        a = _make_entry(1, parent_id=3)
        b = _make_entry(2, parent_id=1)
        c = _make_entry(3, parent_id=2)
        entries = [a, b, c]
        service = _make_service(entries)

        result = await service.get_logbook_data(user_id="u1")
        # All entries should become roots because every chain leads to a cycle
        assert len(result.entries) == 3

    @pytest.mark.asyncio
    async def test_missing_parent_becomes_root(self) -> None:
        """If parent_id refers to a journal not in the result set, treat as root."""
        entry = _make_entry(1, parent_id=999)
        service = _make_service([entry])

        result = await service.get_logbook_data(user_id="u1")
        assert len(result.entries) == 1
        assert result.entries[0].id == 1

    @pytest.mark.asyncio
    async def test_children_not_duplicated(self) -> None:
        """A child should not be added to its parent multiple times."""
        parent = _make_entry(1)
        child = _make_entry(2, parent_id=1)
        # Simulate the same child appearing twice in raw_entries
        entries = [parent, child, child]
        service = _make_service(entries)

        result = await service.get_logbook_data(user_id="u1")
        root = result.entries[0]
        assert len(root.children) == 1

    @pytest.mark.asyncio
    async def test_children_sorted_by_date(self) -> None:
        """Children should be sorted chronologically by event_date_range.start."""
        parent = _make_entry(1)
        child_late = LogbookEntryData(
            id=3,
            title="Later",
            content="",
            event_date_range=EventDateRange(
                start=datetime.datetime(2024, 3, 1, tzinfo=datetime.UTC),
                end=datetime.datetime(2024, 3, 1, tzinfo=datetime.UTC),
            ),
            parent_id=1,
            journal_types=["BUSHWALKING"],
        )
        child_early = LogbookEntryData(
            id=2,
            title="Earlier",
            content="",
            event_date_range=EventDateRange(
                start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
                end=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
            ),
            parent_id=1,
            journal_types=["BUSHWALKING"],
        )
        # Feed in reverse order
        entries = [parent, child_late, child_early]
        service = _make_service(entries)

        result = await service.get_logbook_data(user_id="u1")
        root = result.entries[0]
        assert root.children[0].id == 2  # Earlier first
        assert root.children[1].id == 3

    @pytest.mark.asyncio
    async def test_deep_hierarchy(self) -> None:
        """A 3-level hierarchy should be assembled correctly."""
        grandparent = _make_entry(1)
        parent = _make_entry(2, parent_id=1)
        child = _make_entry(3, parent_id=2)
        entries = [grandparent, parent, child]
        service = _make_service(entries)

        result = await service.get_logbook_data(user_id="u1")
        assert len(result.entries) == 1
        root = result.entries[0]
        assert root.id == 1
        assert len(root.children) == 1
        assert root.children[0].id == 2
        assert len(root.children[0].children) == 1
        assert root.children[0].children[0].id == 3
