"""Each user's records of a non-calendar integration live on their own calendar.

A synthetic calendar shared by every user is owned by whoever synced first, and
a link is unique per calendar, so the id is derived from the integration and the
user (#1510, #1856).
"""

from uuid import NAMESPACE_URL, uuid5

from core_shared.integration_constants import SyntheticCalendar, synthetic_calendar_id

USER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_USER = "1b2c3d4e-0000-4000-8000-fedcbafedcba"


def test_the_id_is_the_same_on_every_call() -> None:
    assert synthetic_calendar_id(SyntheticCalendar.STRAVA, USER) == (
        synthetic_calendar_id(SyntheticCalendar.STRAVA, USER)
    )


def test_each_user_has_their_own_calendar() -> None:
    assert synthetic_calendar_id(SyntheticCalendar.STRAVA, USER) != (
        synthetic_calendar_id(SyntheticCalendar.STRAVA, OTHER_USER)
    )


def test_each_integration_has_its_own_calendar() -> None:
    ids = {synthetic_calendar_id(calendar, USER) for calendar in SyntheticCalendar}
    assert len(ids) == len(SyntheticCalendar)


def test_strava_names_its_calendar_by_the_user() -> None:
    assert synthetic_calendar_id(SyntheticCalendar.STRAVA, USER) == str(
        uuid5(NAMESPACE_URL, f"strava:{USER}")
    )


def test_snipeit_maintenance_keeps_the_ids_migration_0138_wrote() -> None:
    assert synthetic_calendar_id(SyntheticCalendar.SNIPEIT_MAINTENANCE, USER) == str(
        uuid5(NAMESPACE_URL, f"snipeit:maintenance:{USER}")
    )
