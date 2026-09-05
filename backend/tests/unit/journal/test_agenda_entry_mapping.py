"""Unit tests for how a query row becomes an agenda entry.

The adapter collapses ``journal_calendar_info.event_state`` to one boolean at
the edge, and that boolean is the whole of what the agenda knows about
cancellation. The specification allows a cancelled event to be shown marked *or*
omitted, and forbids only the third thing — presenting it as still happening —
so the mapping is pinned here at both ends: a cancelled row is **returned** (not
dropped) and **flagged** (not defaulted), and every other state, including a row
that has none, is not.

The rest of the row is mapped field for field; one test holds that, so a change
to the mapping cannot silently drop a column the card draws.
"""

import datetime
from typing import Any

import pytest

from app.core.journal.adapters.sql.agenda_repository import _to_entry

pytestmark = pytest.mark.unit

NINE_AM = datetime.datetime(2026, 7, 31, 9, tzinfo=datetime.UTC)


def row(**overrides: Any) -> dict[str, Any]:
    """One result row as the query returns it, with the aggregates as text."""
    base: dict[str, Any] = {
        "journal_id": 42,
        "title": "Coffee with Sam",
        "starts_at": NINE_AM,
        "ends_at": NINE_AM + datetime.timedelta(hours=1),
        "is_all_day": False,
        "start_time": datetime.time(9, 0),
        "end_time": datetime.time(10, 0),
        "location": "The good place",
        "timezone": "Australia/Sydney",
        "calendar_color": "#336699",
        "event_state": "confirmed",
        "tags": '[{"id": "tag-1", "name": "social", "color": "#ff0000"}]',
        "participants": '[{"contact_id": 7, "name": "Sam Taylor"}]',
    }
    return {**base, **overrides}


class TestACancelledRow:
    def test_is_returned_flagged_rather_than_dropped(self) -> None:
        """W18: the card needs the entry in order to mark it."""
        entry = _to_entry(row(event_state="cancelled"))

        assert entry.journal_id == 42
        assert entry.is_cancelled is True

    def test_keeps_everything_else_the_card_draws(self) -> None:
        """Cancellation is a marker on a full row, not a reduced row.

        The wireframe strikes the title through and mutes the row; it does not
        take away the time, place or people, so neither does the mapping.
        """
        entry = _to_entry(row(event_state="cancelled"))

        assert entry.title == "Coffee with Sam"
        assert entry.start_time == datetime.time(9, 0)
        assert entry.location == "The good place"
        assert [tag.name for tag in entry.tags] == ["social"]
        assert [person.name for person in entry.participants] == ["Sam Taylor"]


class TestEveryOtherState:
    @pytest.mark.parametrize("state", ["confirmed", "tentative", None])
    def test_is_not_flagged(self, state: str | None) -> None:
        """Only CANCELLED means cancelled — a tentative event is still happening,
        and a row with no state (a journal made in the app rather than synced)
        is the ordinary case, not a suspicious one.
        """
        assert _to_entry(row(event_state=state)).is_cancelled is False

    def test_the_flag_is_read_from_the_row_not_defaulted(self) -> None:
        """Two rows differing only in state map to two different flags."""
        assert _to_entry(row(event_state="cancelled")).is_cancelled is True
        assert _to_entry(row(event_state="confirmed")).is_cancelled is False


class TestTheRestOfTheRow:
    def test_maps_field_for_field(self) -> None:
        entry = _to_entry(row())

        assert entry.journal_id == 42
        assert entry.title == "Coffee with Sam"
        assert entry.is_all_day is False
        assert entry.starts_at == NINE_AM
        assert entry.ends_at == NINE_AM + datetime.timedelta(hours=1)
        assert entry.start_time == datetime.time(9, 0)
        assert entry.end_time == datetime.time(10, 0)
        assert entry.location == "The good place"
        assert entry.timezone == "Australia/Sydney"
        assert entry.calendar_color == "#336699"
        assert entry.tags[0].id == "tag-1"
        assert entry.tags[0].color == "#ff0000"
        assert entry.participants[0].contact_id == 7

    def test_empty_aggregates_map_to_empty_tuples(self) -> None:
        entry = _to_entry(row(tags="[]", participants="[]"))

        assert entry.tags == ()
        assert entry.participants == ()
