"""Unit tests for the journal push's merge against the synced base (#1899)."""

from typing import Any

import pytest
from core_shared.calendar_sync_base import (
    CalendarBase,
    CalendarSyncField,
    description_key,
    location_key,
    summary_key,
    when_key,
)

from calendar_push_merge import (
    UNCONFIRMED_KEY,
    plan_event_push,
    record_event_push,
    unconfirmed_push,
)

pytestmark = pytest.mark.unit

SUMMARY = CalendarSyncField.SUMMARY
DESCRIPTION = CalendarSyncField.DESCRIPTION
LOCATION = CalendarSyncField.LOCATION
WHEN = CalendarSyncField.WHEN

START = {"dateTime": "2026-11-20T01:00:00Z"}
END = {"dateTime": "2026-11-20T02:00:00Z"}
WHEN_KEY = when_key(START, END)


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": "Physio",
        "description": "notes",
        "location": "Clinic",
        "start": START,
        "end": END,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def _agreed(**overrides: str) -> CalendarBase:
    """A base in which both sides agree on ``_payload()``'s values."""
    base = {
        SUMMARY: frozenset({summary_key("Physio")}),
        DESCRIPTION: frozenset({description_key("notes")}),
        LOCATION: frozenset({location_key("Clinic")}),
        WHEN: frozenset({WHEN_KEY}),
    }
    for field, key in overrides.items():
        base[CalendarSyncField(field)] = frozenset({key})
    return base


def _response(**overrides: Any) -> dict[str, Any]:
    """Google's copy of the event after the PATCH."""
    response = _payload(**overrides)
    response["etag"] = '"etag-after"'
    return response


class TestPlanEventPush:
    def test_sends_only_the_fields_local_changed(self) -> None:
        plan = plan_event_push(
            _payload(summary="Physio (mine)"), location="Clinic", base=_agreed()
        )

        assert plan.payload == {"summary": "Physio (mine)"}
        assert plan.sent == {SUMMARY}

    def test_sends_nothing_when_local_changed_nothing(self) -> None:
        plan = plan_event_push(_payload(), location="Clinic", base=_agreed())

        assert plan.payload == {}
        assert plan.sent == frozenset()

    def test_sends_start_and_end_together(self) -> None:
        moved_end = {"date": "2026-11-21"}
        plan = plan_event_push(
            _payload(start={"date": "2026-11-20"}, end=moved_end),
            location="Clinic",
            base=_agreed(),
        )

        assert plan.payload == {"start": {"date": "2026-11-20"}, "end": moved_end}

    def test_sends_a_cleared_location_as_empty(self) -> None:
        plan = plan_event_push(_payload(location=None), location=None, base=_agreed())

        assert plan.payload == {"location": ""}

    def test_without_a_base_sends_everything_as_before(self) -> None:
        payload = _payload(location=None)

        plan = plan_event_push(payload, location=None, base=None)

        assert plan.payload == payload
        assert plan.sent == {SUMMARY, DESCRIPTION, WHEN}

    def test_a_field_the_base_lacks_counts_as_changed(self) -> None:
        base = dict(_agreed())
        del base[SUMMARY]

        plan = plan_event_push(_payload(), location="Clinic", base=base)

        assert plan.payload == {"summary": "Physio"}

    def test_a_private_description_is_never_merged(self) -> None:
        plan = plan_event_push(
            _payload(description=None), location="Clinic", base=_agreed()
        )

        assert DESCRIPTION not in plan.local
        assert plan.payload == {}


class TestRecordEventPush:
    def test_a_sent_field_records_both_spellings(self) -> None:
        # Google answering with a spelling that keys differently from the one
        # sent: both must stay in the base, or the next push or pull would
        # read the other one as a change.
        plan = plan_event_push(
            _payload(summary="Physio (mine)"), location="Clinic", base=_agreed()
        )

        record = record_event_push(
            plan, base=_agreed(), response=_response(summary="physio (MINE)")
        )

        assert summary_key("Physio (mine)") != summary_key("physio (MINE)")
        assert record.agreed[SUMMARY] == {
            summary_key("Physio (mine)"),
            summary_key("physio (MINE)"),
        }
        assert SUMMARY not in record.seeded
        assert record.pending_import is False

    def test_google_winning_an_importable_field_leaves_its_base_and_marks_import(
        self,
    ) -> None:
        # Left out of the write altogether: a pull may have recorded Google's
        # value since this push read the base, and must not lose it.
        plan = plan_event_push(
            _payload(description="mine"), location="Clinic", base=_agreed()
        )

        record = record_event_push(
            plan, base=_agreed(), response=_response(summary="Physio (Google)")
        )

        assert SUMMARY not in record.agreed
        assert SUMMARY not in record.seeded
        assert record.pending_import is True

    def test_google_winning_the_description_alone_marks_no_import(self) -> None:
        # A pull never writes the description on an update: there would be
        # nothing for it to import.
        plan = plan_event_push(
            _payload(summary="mine"), location="Clinic", base=_agreed()
        )

        record = record_event_push(
            plan, base=_agreed(), response=_response(summary="mine", description="G")
        )

        assert DESCRIPTION not in record.agreed
        assert DESCRIPTION not in record.seeded
        assert record.pending_import is False

    def test_a_reformatted_sent_field_is_not_a_google_win(self) -> None:
        plan = plan_event_push(
            _payload(start=START, end={"dateTime": "2026-11-20T03:00:00Z"}),
            location="Clinic",
            base=_agreed(),
        )

        record = record_event_push(
            plan,
            base=_agreed(),
            response=_response(
                start={"dateTime": "2026-11-20T12:00:00+11:00"},
                end={"dateTime": "2026-11-20T14:00:00+11:00"},
            ),
        )

        assert record.pending_import is False

    def test_without_a_base_an_untouched_field_google_holds_is_imported(
        self,
    ) -> None:
        plan = plan_event_push(_payload(location=None), location=None, base=None)

        record = record_event_push(
            plan, base=None, response=_response(location="Clinic")
        )

        assert record.seeded[LOCATION] == {location_key(None)}
        assert LOCATION not in record.agreed
        assert record.pending_import is True

    def test_a_private_description_leaves_the_base_it_had(self) -> None:
        plan = plan_event_push(
            _payload(description=None, summary="mine"),
            location="Clinic",
            base=_agreed(),
        )

        record = record_event_push(
            plan, base=_agreed(), response=_response(summary="mine")
        )

        assert DESCRIPTION not in record.agreed
        assert DESCRIPTION not in record.seeded


class TestUnconfirmedPush:
    def test_marks_every_field_the_push_sent(self) -> None:
        plan = plan_event_push(
            _payload(summary="mine", location="Home"), location="Home", base=_agreed()
        )

        assert unconfirmed_push(plan) == {
            SUMMARY: frozenset({UNCONFIRMED_KEY}),
            LOCATION: frozenset({UNCONFIRMED_KEY}),
        }

    def test_the_next_push_resends_a_field_reverted_meanwhile(self) -> None:
        # Google may hold the value the failed push sent: local's earlier value
        # is no longer known to agree with it.
        failed = plan_event_push(
            _payload(summary="mine"), location="Clinic", base=_agreed()
        )
        base = {**_agreed(), **unconfirmed_push(failed)}

        plan = plan_event_push(_payload(), location="Clinic", base=base)

        assert plan.payload == {"summary": "Physio"}
