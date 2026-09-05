"""Unit tests for the day window two domains share.

The window was born in the tasks domain, where ITER18-001 Phase 14 built it for
"tasks due between today and seven days ahead". ITER18-004 Phase 11 needs the
**same** span for upcoming contact dates — the specification says the dates
section covers "the next seven days, matching the tasks window" — so the
arithmetic and the bound moved here, where neither domain owns them.

What each domain keeps is its **error type**: a bad ``days_ahead`` is a 400
about that domain's parameter, and a contacts surface raising
``TaskValidationError`` would be nonsense. So this module raises a neutral
:class:`DateWindowError` and each caller translates it. The translation is the
thing worth testing on the caller's side; what is tested here is that there is
exactly one definition of where the window starts, where it ends, and how far
it may reach.
"""

from __future__ import annotations

import datetime

import pytest

from core_shared.models.date_window import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    MAX_UPCOMING_DAYS_AHEAD,
    DateWindowError,
    UpcomingWindow,
    upcoming_window,
)

pytestmark = pytest.mark.unit

TODAY = datetime.date(2026, 8, 11)


class TestTheArithmetic:
    """Where the window starts, where it ends, and what it remembers."""

    def test_it_runs_from_today_to_days_ahead_after_it(self) -> None:
        window = upcoming_window(TODAY, 7)

        assert window.first_day == TODAY
        assert window.last_day == datetime.date(2026, 8, 18)
        assert window.days_ahead == 7

    def test_the_default_is_seven_days(self) -> None:
        assert DEFAULT_UPCOMING_DAYS_AHEAD == 7
        assert upcoming_window(TODAY) == upcoming_window(TODAY, 7)

    def test_zero_days_ahead_is_today_alone(self) -> None:
        """A legitimate request, not an empty window."""
        window = upcoming_window(TODAY, 0)

        assert window.first_day == window.last_day == TODAY
        assert window.contains(TODAY)

    def test_it_crosses_a_year_boundary(self) -> None:
        window = upcoming_window(datetime.date(2026, 12, 29), 7)

        assert window.last_day == datetime.date(2027, 1, 5)

    def test_the_window_is_frozen(self) -> None:
        """Derived entirely from its two arguments, so there is nothing to edit."""
        window = upcoming_window(TODAY, 7)

        with pytest.raises(AttributeError):
            window.first_day = TODAY  # type: ignore[misc]


class TestBothEndsAreInclusive:
    """ "Inclusive" is the word an off-by-one gets wrong, so both edges are pinned."""

    @pytest.fixture
    def window(self) -> UpcomingWindow:
        return upcoming_window(TODAY, 7)

    def test_today_is_in_the_window(self, window: UpcomingWindow) -> None:
        assert window.contains(TODAY)

    def test_yesterday_is_not(self, window: UpcomingWindow) -> None:
        assert not window.contains(TODAY - datetime.timedelta(days=1))

    def test_the_last_day_is_in_the_window(self, window: UpcomingWindow) -> None:
        assert window.contains(datetime.date(2026, 8, 18))

    def test_the_day_after_the_last_is_not(self, window: UpcomingWindow) -> None:
        assert not window.contains(datetime.date(2026, 8, 19))


class TestTheBound:
    """The window is bounded here so no surface can reach past it another way."""

    def test_the_maximum_is_ninety_days(self) -> None:
        assert MAX_UPCOMING_DAYS_AHEAD == 90
        assert upcoming_window(TODAY, 90).days_ahead == 90

    def test_a_negative_window_is_refused(self) -> None:
        with pytest.raises(DateWindowError) as excinfo:
            upcoming_window(TODAY, -1)

        assert "days_ahead" in str(excinfo.value)

    def test_a_window_past_the_maximum_is_refused(self) -> None:
        with pytest.raises(DateWindowError) as excinfo:
            upcoming_window(TODAY, 91)

        assert "90" in str(excinfo.value)

    def test_the_error_names_the_field_and_the_reason_separately(self) -> None:
        """So a caller can translate it into its own domain's validation error."""
        with pytest.raises(DateWindowError) as excinfo:
            upcoming_window(TODAY, 91)

        assert excinfo.value.field == "days_ahead"
        assert "91" in excinfo.value.reason
