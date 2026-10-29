"""Unit tests for the calendar event fields a journal push merges (#1899).

Keys are compared across three readings of one event — the journal's, the
pull's and the push response's — so each test pins two spellings that must key
equal, or two values that must not.
"""

from datetime import UTC, datetime, time
from uuid import uuid4

import pytest

from core_shared.calendar_sync_base import (
    IMPORTABLE_ON_UPDATE,
    CalendarSyncField,
    changed,
    description_key,
    local_when,
    location_key,
    summary_key,
    when_key,
)
from core_shared.models.journals import CalendarInfo

pytestmark = pytest.mark.unit


class TestSummaryKey:
    def test_ignores_surrounding_whitespace(self) -> None:
        assert summary_key("  Lunch ") == summary_key("Lunch")

    def test_a_blank_summary_is_the_untitled_title_a_pull_gives_it(self) -> None:
        assert summary_key("") == summary_key("Untitled Event")
        assert summary_key(None) == summary_key("Untitled Event")

    def test_differs_for_a_different_title(self) -> None:
        assert summary_key("Lunch") != summary_key("Dinner")


class TestDescriptionKey:
    def test_none_and_empty_are_the_same(self) -> None:
        assert description_key(None) == description_key("")

    def test_ignores_surrounding_whitespace(self) -> None:
        assert description_key("notes\n") == description_key("notes")


class TestLocationKey:
    def test_none_and_empty_are_the_same(self) -> None:
        assert location_key(None) == location_key("")

    def test_differs_for_a_different_place(self) -> None:
        assert location_key("Sydney") != location_key("Melbourne")


class TestWhenKey:
    def test_a_timed_instant_keys_the_same_in_any_zone(self) -> None:
        sent = when_key(
            {"dateTime": "2026-10-29T00:00:00Z", "timeZone": "Australia/Sydney"},
            {"dateTime": "2026-10-29T01:00:00Z", "timeZone": "Australia/Sydney"},
        )
        echoed = when_key(
            {"dateTime": "2026-10-29T11:00:00+11:00", "timeZone": "Australia/Sydney"},
            {"dateTime": "2026-10-29T12:00:00+11:00", "timeZone": "Australia/Sydney"},
        )

        assert sent == echoed

    def test_a_moved_end_changes_the_key(self) -> None:
        start = {"dateTime": "2026-10-29T00:00:00Z"}

        assert when_key(start, {"dateTime": "2026-10-29T01:00:00Z"}) != when_key(
            start, {"dateTime": "2026-10-29T02:00:00Z"}
        )

    def test_an_all_day_event_keys_by_date_alone(self) -> None:
        in_a_zone = when_key(
            {"date": "2026-10-29", "timeZone": "Australia/Sydney"},
            {"date": "2026-10-30", "timeZone": "Australia/Sydney"},
        )

        assert in_a_zone == when_key({"date": "2026-10-29"}, {"date": "2026-10-30"})

    def test_switching_between_timed_and_all_day_changes_the_key(self) -> None:
        all_day = when_key({"date": "2026-10-29"}, {"date": "2026-10-30"})
        timed = when_key(
            {"dateTime": "2026-10-29T00:00:00Z"}, {"dateTime": "2026-10-30T00:00:00Z"}
        )

        assert all_day != timed

    def test_a_dateless_block_keys_apart_from_any_date(self) -> None:
        dateless = when_key({}, {})

        assert dateless != when_key({"date": "2026-10-29"}, {"date": "2026-10-30"})


class TestLocalWhen:
    def _info(self, **overrides: object) -> CalendarInfo:
        fields: dict[str, object] = {"calendar_id": uuid4(), "validate": False}
        fields.update(overrides)
        return CalendarInfo(**fields)  # type: ignore[arg-type]

    def test_an_all_day_event_without_a_zone_reads_its_date_in_the_users(
        self,
    ) -> None:
        sydney_midnight = datetime(2026, 10, 28, 13, tzinfo=UTC)

        start, end = local_when(
            sydney_midnight,
            sydney_midnight,
            self._info(is_all_day=True),
            user_timezone="Australia/Sydney",
        )

        assert start == {"date": "2026-10-29"}
        assert end == {"date": "2026-10-30"}

    def test_a_timed_event_ignores_the_users_zone(self) -> None:
        start, _ = local_when(
            datetime(2026, 10, 29, 1, tzinfo=UTC),
            datetime(2026, 10, 29, 2, tzinfo=UTC),
            self._info(start_time=time(9), end_time=time(10)),
            user_timezone="Australia/Sydney",
        )

        assert start == {"dateTime": "2026-10-29T01:00:00Z"}

    def test_keys_the_same_as_googles_echo_of_the_anchored_times(self) -> None:
        # The stored instant is an hour off the clock time the row records:
        # the push re-anchors it, so the key must too, or every push would
        # see a local change to the times.
        start, end = local_when(
            datetime(2026, 10, 28, 23, tzinfo=UTC),
            datetime(2026, 10, 29, 0, tzinfo=UTC),
            self._info(
                start_time=time(11), end_time=time(12), timezone="Australia/Sydney"
            ),
            user_timezone=None,
        )

        assert when_key(start, end) == when_key(
            {"dateTime": "2026-10-29T11:00:00+11:00"},
            {"dateTime": "2026-10-29T12:00:00+11:00"},
        )


class TestChanged:
    def test_a_key_in_the_base_is_unchanged(self) -> None:
        assert not changed("a", frozenset({"a", "b"}))

    def test_a_key_outside_the_base_is_changed(self) -> None:
        assert changed("c", frozenset({"a", "b"}))

    def test_without_a_base_every_key_is_changed(self) -> None:
        assert changed("a", None)


def test_description_is_not_importable_on_update() -> None:
    assert CalendarSyncField.DESCRIPTION not in IMPORTABLE_ON_UPDATE
    assert IMPORTABLE_ON_UPDATE == {
        CalendarSyncField.SUMMARY,
        CalendarSyncField.LOCATION,
        CalendarSyncField.WHEN,
    }
