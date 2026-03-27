"""Unit tests for journal API converters."""

from datetime import UTC, datetime

from core_shared.models.journals.entities import Journal
from core_shared.models.journals.value_objects import EventDateRange

from app.api.journals.converters import JournalConverter


class TestJournalConverterConvertChildren:
    """Tests for JournalConverter._convert_children."""

    def _make_journal(
        self,
        journal_id: int,
        title: str = "Test",
        start: datetime | None = None,
    ) -> Journal:
        start_dt = start or datetime(2026, 3, 1, tzinfo=UTC)
        return Journal(
            id=journal_id,
            user_id="user-1",
            title=title,
            content="",
            event_date_range=EventDateRange(
                start=start_dt,
                end=max(start_dt, datetime(2026, 12, 31, tzinfo=UTC)),
            ),
        )

    def test_returns_none_when_children_is_none(self) -> None:
        result = JournalConverter._convert_children(None)
        assert result is None

    def test_returns_empty_list_when_no_children(self) -> None:
        result = JournalConverter._convert_children([])
        assert result == []

    def test_includes_id_and_title(self) -> None:
        child = self._make_journal(10, title="Child Entry")
        result = JournalConverter._convert_children([child])
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "10"
        assert result[0]["title"] == "Child Entry"

    def test_includes_date_from_event_date_range(self) -> None:
        start = datetime(2026, 6, 15, 10, 30, tzinfo=UTC)
        child = self._make_journal(1, start=start)
        result = JournalConverter._convert_children([child])
        assert result is not None
        assert result[0]["date"] == start.isoformat()

    def test_date_is_none_when_event_date_range_start_is_none(self) -> None:
        child = self._make_journal(1)
        # Bypass EventDateRange validation to simulate a None start
        object.__setattr__(child.event_date_range, "start", None)
        result = JournalConverter._convert_children([child])
        assert result is not None
        assert result[0]["date"] is None

    def test_types_empty_when_no_mapping_provided(self) -> None:
        child = self._make_journal(1)
        result = JournalConverter._convert_children([child])
        assert result is not None
        assert result[0]["types"] == []

    def test_types_from_children_types_mapping(self) -> None:
        child1 = self._make_journal(1, title="Event Child")
        child2 = self._make_journal(2, title="Note Child")
        children_types = {
            1: ["event", "mood_rating"],
            2: ["plan"],
        }
        result = JournalConverter._convert_children([child1, child2], children_types)
        assert result is not None
        assert result[0]["types"] == ["event", "mood_rating"]
        assert result[1]["types"] == ["plan"]

    def test_types_empty_for_child_not_in_mapping(self) -> None:
        child = self._make_journal(99, title="Unknown Type Child")
        children_types = {1: ["event"]}
        result = JournalConverter._convert_children([child], children_types)
        assert result is not None
        assert result[0]["types"] == []

    def test_multiple_children_with_mixed_data(self) -> None:
        start1 = datetime(2026, 1, 10, tzinfo=UTC)
        start2 = datetime(2026, 2, 20, tzinfo=UTC)
        child1 = self._make_journal(10, title="A", start=start1)
        child2 = self._make_journal(20, title="B", start=start2)
        children_types = {10: ["event"]}

        result = JournalConverter._convert_children([child1, child2], children_types)
        assert result is not None
        assert len(result) == 2
        assert result[0] == {
            "id": "10",
            "title": "A",
            "types": ["event"],
            "date": start1.isoformat(),
        }
        assert result[1] == {
            "id": "20",
            "title": "B",
            "types": [],
            "date": start2.isoformat(),
        }
