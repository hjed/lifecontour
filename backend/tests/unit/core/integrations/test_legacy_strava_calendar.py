"""An event naming the old shared Strava calendar is read as naming the user's own.

Until #1856 every user's Strava activities were linked on one calendar. Events
the old worker sent before the migration moved those links can still be in the
stream, so they are re-homed onto the sender's calendar as they arrive.
"""

from typing import Any

from core_shared.integration_constants import (
    LEGACY_SHARED_STRAVA_CALENDAR_ID,
    SyntheticCalendar,
    synthetic_calendar_id,
)

from app.core.integrations.journal_outbox_event_processor import (
    rehome_legacy_strava_calendar,
)

USER = "strava-user"


def _event_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "integration_source": "strava",
        "calendar_id": LEGACY_SHARED_STRAVA_CALENDAR_ID,
        "calendar_info_data": {"calendar_id": LEGACY_SHARED_STRAVA_CALENDAR_ID},
        "journal_data": {"user_id": USER},
        "external_event_id": "strava:1",
    }
    data.update(overrides)
    return data


def test_both_calendar_ids_move_to_the_users_own_calendar() -> None:
    own = synthetic_calendar_id(SyntheticCalendar.STRAVA, USER)

    rehomed = rehome_legacy_strava_calendar(_event_data())

    assert rehomed["calendar_id"] == own
    assert rehomed["calendar_info_data"]["calendar_id"] == own


def test_a_cancellation_with_no_calendar_info_is_rehomed_too() -> None:
    data = _event_data()
    del data["calendar_info_data"]

    rehomed = rehome_legacy_strava_calendar(data)

    assert rehomed["calendar_id"] == synthetic_calendar_id(
        SyntheticCalendar.STRAVA, USER
    )
    assert "calendar_info_data" not in rehomed


def test_the_event_it_was_given_is_left_alone() -> None:
    data = _event_data()

    rehome_legacy_strava_calendar(data)

    assert data == _event_data()


def test_an_event_on_any_other_calendar_is_unchanged() -> None:
    data = _event_data(calendar_id="5b0c9a52-0000-4000-8000-000000000000")

    assert rehome_legacy_strava_calendar(data) == data


def test_another_sources_event_is_unchanged() -> None:
    data = _event_data(integration_source="google")

    assert rehome_legacy_strava_calendar(data) == data


def test_an_event_naming_no_user_is_unchanged() -> None:
    data = _event_data(journal_data={})

    assert rehome_legacy_strava_calendar(data) == data
