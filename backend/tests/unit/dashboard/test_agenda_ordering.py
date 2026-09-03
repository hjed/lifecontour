"""Unit tests for the agenda's ordering rule.

The wireframe states the order in two clauses — all-day entries pinned above
timed ones (**W12**), timed ones ascending by start (**W13**) — and the whole of
this phase's product is that rule. It is only meaningful at its boundaries, so
each boundary gets a test: several all-day entries together, entries sharing a
start, an entry that began on a previous day, and the day with nothing on it.

**The sort key for a timed entry is the stored instant, not its clock time.** A
journal that began yesterday and runs through today carries a ``start_time``
belonging to another day; ordering by it would interleave that entry with today's
by an hour that never happened today. The instant is also the key the day window
already compares against, so the list is ordered by the same quantity that
decided which entries are on it.
"""

import datetime

import pytest

from app.core.dashboard.models.sections import AgendaEntry
from app.core.dashboard.services.agenda_section import order_agenda_entries

pytestmark = pytest.mark.unit

# A fixed local day, so every instant below is readable against the same anchor.
TODAY = datetime.date(2026, 7, 31)


def instant(
    hour: int, minute: int = 0, *, day: datetime.date = TODAY
) -> datetime.datetime:
    """An aware UTC instant on ``day``, written as the hour a reader sees."""
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=datetime.UTC
    )


def entry(
    journal_id: int,
    *,
    title: str = "An event",
    all_day: bool = False,
    starts_at: datetime.datetime | None = None,
    ends_at: datetime.datetime | None = None,
    cancelled: bool = False,
) -> AgendaEntry:
    """One agenda entry, with only the fields the ordering rule reads set."""
    start = starts_at if starts_at is not None else instant(9)
    return AgendaEntry(
        journal_id=journal_id,
        title=title,
        is_all_day=all_day,
        starts_at=start,
        ends_at=ends_at if ends_at is not None else start + datetime.timedelta(hours=1),
        is_cancelled=cancelled,
    )


def ids(entries: tuple[AgendaEntry, ...]) -> list[int]:
    return [item.journal_id for item in entries]


class TestAllDayEntriesArePinnedAbove:
    def test_an_all_day_entry_precedes_a_timed_one_that_starts_earlier(self) -> None:
        """W12 is a pin, not a tie-break: the clock does not rescue the timed row."""
        timed = entry(1, starts_at=instant(6))
        all_day = entry(2, all_day=True, starts_at=instant(0))

        ordered = order_agenda_entries([timed, all_day])

        assert ids(ordered) == [2, 1]

    def test_several_all_day_entries_all_sit_above_every_timed_entry(self) -> None:
        entries = [
            entry(1, starts_at=instant(8)),
            entry(2, all_day=True),
            entry(3, starts_at=instant(9)),
            entry(4, all_day=True),
            entry(5, all_day=True),
        ]

        ordered = order_agenda_entries(entries)

        assert [item.is_all_day for item in ordered] == [True, True, True, False, False]

    def test_several_all_day_entries_hold_a_deterministic_order(self) -> None:
        """Two all-day entries on the same day have no time to separate them.

        They are still ordered — by their stored instant, then by journal id — so
        the same day renders the same way on every request rather than in
        whatever order the database happened to return.
        """
        entries = [
            entry(9, all_day=True, starts_at=instant(0)),
            entry(3, all_day=True, starts_at=instant(0)),
            entry(7, all_day=True, starts_at=instant(0)),
        ]

        assert ids(order_agenda_entries(entries)) == [3, 7, 9]


class TestTimedEntriesAscendByStart:
    def test_they_are_ordered_by_the_instant_they_begin(self) -> None:
        entries = [
            entry(1, starts_at=instant(17)),
            entry(2, starts_at=instant(9, 30)),
            entry(3, starts_at=instant(12)),
        ]

        assert ids(order_agenda_entries(entries)) == [2, 3, 1]

    def test_entries_sharing_a_start_break_the_tie_on_journal_id(self) -> None:
        """Two things really can start at once; the order must still be stable."""
        entries = [
            entry(8, starts_at=instant(14)),
            entry(2, starts_at=instant(14)),
            entry(5, starts_at=instant(14)),
        ]

        assert ids(order_agenda_entries(entries)) == [2, 5, 8]


class TestAMultiDayJournalOverlappingToday:
    def test_it_sorts_by_when_it_began_not_by_when_today_began(self) -> None:
        """A trip that started yesterday is already under way, so it leads.

        Ordering by the clock component instead would place its 20:00 start after
        this morning's meetings, describing a day the user is not having.
        """
        yesterday = TODAY - datetime.timedelta(days=1)
        ongoing = entry(
            1,
            title="Three days on the river",
            starts_at=instant(20, day=yesterday),
            ends_at=instant(16, day=TODAY + datetime.timedelta(days=1)),
        )
        this_morning = entry(2, starts_at=instant(9))

        assert ids(order_agenda_entries([this_morning, ongoing])) == [1, 2]

    def test_an_all_day_multi_day_entry_is_still_pinned_above_timed_ones(self) -> None:
        yesterday = TODAY - datetime.timedelta(days=1)
        ongoing = entry(
            1, all_day=True, starts_at=instant(0, day=yesterday), ends_at=instant(23)
        )
        early = entry(2, starts_at=instant(6))

        assert ids(order_agenda_entries([early, ongoing])) == [1, 2]


class TestTheWholeOrdering:
    def test_a_mixed_day_comes_out_in_wireframe_order(self) -> None:
        """W12 then W13, asserted once over a day with every case in it."""
        yesterday = TODAY - datetime.timedelta(days=1)
        entries = [
            entry(1, title="Standup", starts_at=instant(9)),
            entry(2, title="Public holiday", all_day=True, starts_at=instant(0)),
            entry(3, title="Dinner", starts_at=instant(19)),
            entry(
                4,
                title="Conference",
                all_day=True,
                starts_at=instant(0, day=yesterday),
                ends_at=instant(23),
            ),
            entry(5, title="Lunch", starts_at=instant(12, 30)),
        ]

        ordered = order_agenda_entries(entries)

        assert [item.title for item in ordered] == [
            "Conference",
            "Public holiday",
            "Standup",
            "Lunch",
            "Dinner",
        ]


class TestACancelledEntry:
    """Cancellation is a marker, not a position: the rule neither drops nor moves it.

    The specification allows a cancelled event to be shown marked or omitted,
    and *omitted* is a decision for a surface, not for the ordering rule — a
    rule that filtered would take the choice away from every card that reads it.
    """

    def test_keeps_its_place_among_the_timed_entries(self) -> None:
        ordered = order_agenda_entries(
            [
                entry(1, starts_at=instant(17)),
                entry(2, starts_at=instant(12), cancelled=True),
                entry(3, starts_at=instant(9)),
            ]
        )

        assert ids(ordered) == [3, 2, 1]
        assert [item.is_cancelled for item in ordered] == [False, True, False]

    def test_a_cancelled_all_day_entry_is_still_pinned_above(self) -> None:
        ordered = order_agenda_entries(
            [entry(1, starts_at=instant(0)), entry(2, all_day=True, cancelled=True)]
        )

        assert ids(ordered) == [2, 1]


class TestTheEmptyDay:
    def test_nothing_scheduled_orders_to_nothing(self) -> None:
        """A day with no events is an answer, and this is the shape of it."""
        assert order_agenda_entries([]) == ()


class TestTheRuleIsPure:
    def test_it_leaves_the_sequence_it_was_given_alone(self) -> None:
        """Callers pass a repository's list; sorting it in place would surprise."""
        entries = [entry(1, starts_at=instant(17)), entry(2, all_day=True)]
        original = list(entries)

        order_agenda_entries(entries)

        assert entries == original

    def test_it_returns_a_tuple_so_the_section_payload_stays_frozen(self) -> None:
        assert isinstance(order_agenda_entries([entry(1)]), tuple)
