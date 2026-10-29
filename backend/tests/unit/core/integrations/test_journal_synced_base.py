"""Unit tests for what an inbound calendar update may change (#1899)."""

from datetime import time
from uuid import uuid4

import pytest
from core_shared.calendar_sync_base import CalendarSyncField
from core_shared.models.journals import CalendarInfo

from app.core.integrations.journal_synced_base import (
    kept_calendar_info_data,
    protected_journal_fields,
)

pytestmark = pytest.mark.unit

SUMMARY = CalendarSyncField.SUMMARY
DESCRIPTION = CalendarSyncField.DESCRIPTION
LOCATION = CalendarSyncField.LOCATION
WHEN = CalendarSyncField.WHEN
FULL_BASE = {field: frozenset({"k"}) for field in CalendarSyncField}


class TestProtectedJournalFields:
    def test_protects_only_what_local_changed(self) -> None:
        assert protected_journal_fields(
            FULL_BASE, frozenset({SUMMARY}), local_edits=True
        ) == {"title"}

    def test_a_local_time_change_protects_both_bounds(self) -> None:
        assert protected_journal_fields(
            FULL_BASE, frozenset({WHEN}), local_edits=False
        ) == {"event_date_range_start", "event_date_range_end"}

    def test_location_is_not_a_journal_field(self) -> None:
        assert (
            protected_journal_fields(
                FULL_BASE, frozenset({LOCATION}), local_edits=False
            )
            == frozenset()
        )

    def test_a_field_the_base_lacks_falls_back_to_the_local_edit_rule(
        self,
    ) -> None:
        base = {WHEN: frozenset({"k"}), LOCATION: frozenset({"k"})}

        assert protected_journal_fields(base, frozenset(), local_edits=True) == {
            "title",
            "content",
        }
        assert protected_journal_fields(base, frozenset(), local_edits=False) == (
            frozenset()
        )


class TestKeptCalendarInfoData:
    STORED = CalendarInfo(
        calendar_id=uuid4(),
        is_all_day=False,
        start_time=time(9),
        end_time=time(10),
        timezone="Australia/Sydney",
        location="Home visit",
        validate=False,
    )
    INBOUND = {
        "calendar_id": "c",
        "is_all_day": True,
        "start_time": None,
        "end_time": None,
        "timezone": "UTC",
        "location": "New clinic",
    }

    def test_takes_the_inbound_values_local_left_alone(self) -> None:
        assert kept_calendar_info_data(self.INBOUND, self.STORED, frozenset()) == (
            self.INBOUND
        )

    def test_keeps_a_local_location(self) -> None:
        kept = kept_calendar_info_data(self.INBOUND, self.STORED, frozenset({LOCATION}))

        assert kept["location"] == "Home visit"
        assert kept["is_all_day"] is True

    def test_keeps_local_times_together(self) -> None:
        kept = kept_calendar_info_data(self.INBOUND, self.STORED, frozenset({WHEN}))

        assert (
            kept["is_all_day"],
            kept["start_time"],
            kept["end_time"],
            kept["timezone"],
        ) == (False, time(9), time(10), "Australia/Sydney")
        assert kept["location"] == "New clinic"
