"""
Unit tests for outbound Google date transformation in the worker.

Tests the conversion of internal ImportantDate entities to Google People API
birthdays and events format, including local-only filtering rules.
"""

import sys
from typing import Any

sys.path.insert(0, "/core_shared")

# Import the worker functions under test
from worker import (
    _transform_contact_to_google_person,
    _transform_important_dates_to_google,
)


class TestTransformImportantDatesToGoogle:
    """Test outbound transformation of ImportantDate dicts to Google format."""

    def test_birthday_full_precision(self) -> None:
        """BIRTHDAY/FULL → Google birthdays with year, month, day."""
        dates = [
            {
                "date_type": "birthday",
                "precision": "full",
                "year": 1990,
                "month": 5,
                "day": 20,
            }
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 1
        assert birthdays[0] == {"date": {"year": 1990, "month": 5, "day": 20}}
        assert len(events) == 0

    def test_birthday_day_month_precision(self) -> None:
        """BIRTHDAY/DAY_MONTH → Google birthdays with year=0."""
        dates = [
            {
                "date_type": "birthday",
                "precision": "day_month",
                "year": None,
                "month": 3,
                "day": 15,
            }
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 1
        assert birthdays[0] == {"date": {"year": 0, "month": 3, "day": 15}}

    def test_birthday_year_precision(self) -> None:
        """BIRTHDAY/YEAR → Google birthdays with month=0, day=0."""
        dates = [
            {
                "date_type": "birthday",
                "precision": "year",
                "year": 1985,
                "month": None,
                "day": None,
            }
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 1
        assert birthdays[0] == {"date": {"year": 1985, "month": 0, "day": 0}}

    def test_marriage_anniversary_maps_to_event(self) -> None:
        """MARRIAGE_ANNIVERSARY → Google events with type='anniversary'."""
        dates = [
            {
                "date_type": "marriage_anniversary",
                "precision": "full",
                "year": 2015,
                "month": 6,
                "day": 20,
            }
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 0
        assert len(events) == 1
        assert events[0] == {
            "date": {"year": 2015, "month": 6, "day": 20},
            "type": "anniversary",
        }

    def test_work_anniversary_filtered_out(self) -> None:
        """WORK_ANNIVERSARY is local-only and must not appear in output."""
        dates = [
            {
                "date_type": "work_anniversary",
                "precision": "full",
                "year": 2020,
                "month": 1,
                "day": 1,
            }
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 0
        assert len(events) == 0

    def test_first_met_filtered_out(self) -> None:
        """FIRST_MET is local-only and must not appear in output."""
        dates = [
            {
                "date_type": "first_met",
                "precision": "full",
                "year": 2019,
                "month": 7,
                "day": 4,
            }
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 0
        assert len(events) == 0

    def test_custom_filtered_out(self) -> None:
        """CUSTOM dates are local-only and must not appear in output."""
        dates = [
            {
                "date_type": "custom",
                "precision": "full",
                "year": 2021,
                "month": 12,
                "day": 25,
                "custom_date_type_id": 1,
            }
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 0
        assert len(events) == 0

    def test_mixed_dates_only_supported_in_output(self) -> None:
        """Only BIRTHDAY and MARRIAGE_ANNIVERSARY appear in Google output."""
        dates = [
            {
                "date_type": "birthday",
                "precision": "full",
                "year": 1990,
                "month": 5,
                "day": 20,
            },
            {
                "date_type": "marriage_anniversary",
                "precision": "day_month",
                "year": None,
                "month": 6,
                "day": 20,
            },
            {
                "date_type": "work_anniversary",
                "precision": "full",
                "year": 2020,
                "month": 1,
                "day": 1,
            },
            {
                "date_type": "first_met",
                "precision": "full",
                "year": 2019,
                "month": 7,
                "day": 4,
            },
            {
                "date_type": "custom",
                "precision": "year",
                "year": 2021,
                "month": None,
                "day": None,
            },
        ]
        birthdays, events = _transform_important_dates_to_google(dates)

        assert len(birthdays) == 1
        assert len(events) == 1
        assert birthdays[0]["date"]["year"] == 1990
        assert events[0]["type"] == "anniversary"
        assert events[0]["date"]["year"] == 0  # day_month precision

    def test_empty_dates_list(self) -> None:
        """Empty dates list produces empty output."""
        birthdays, events = _transform_important_dates_to_google([])

        assert len(birthdays) == 0
        assert len(events) == 0


class TestTransformContactToGooglePersonDates:
    """Test that _transform_contact_to_google_person includes date fields."""

    def test_includes_birthdays_and_events(self) -> None:
        """Contact with dates produces birthdays and events in person data."""
        contact: dict[str, Any] = {
            "first_name": "Test",
            "last_name": "User",
            "methods": [],
            "addresses": [],
            "notes": [],
            "important_dates": [
                {
                    "date_type": "birthday",
                    "precision": "full",
                    "year": 1990,
                    "month": 5,
                    "day": 20,
                },
                {
                    "date_type": "marriage_anniversary",
                    "precision": "full",
                    "year": 2015,
                    "month": 6,
                    "day": 20,
                },
            ],
        }

        person_data = _transform_contact_to_google_person(contact)

        assert "birthdays" in person_data
        assert len(person_data["birthdays"]) == 1
        assert "events" in person_data
        assert len(person_data["events"]) == 1

    def test_no_dates_omits_keys(self) -> None:
        """Contact without dates does not include birthdays/events."""
        contact: dict[str, Any] = {
            "first_name": "Test",
            "last_name": "User",
            "methods": [],
            "addresses": [],
            "notes": [],
        }

        person_data = _transform_contact_to_google_person(contact)

        assert "birthdays" not in person_data
        assert "events" not in person_data

    def test_empty_dates_omits_keys(self) -> None:
        """Contact with empty important_dates list does not include keys."""
        contact: dict[str, Any] = {
            "first_name": "Test",
            "last_name": "User",
            "methods": [],
            "addresses": [],
            "notes": [],
            "important_dates": [],
        }

        person_data = _transform_contact_to_google_person(contact)

        assert "birthdays" not in person_data
        assert "events" not in person_data

    def test_local_only_dates_omits_keys(self) -> None:
        """Contact with only local-only date types still omits Google keys."""
        contact: dict[str, Any] = {
            "first_name": "Test",
            "last_name": "User",
            "methods": [],
            "addresses": [],
            "notes": [],
            "important_dates": [
                {
                    "date_type": "work_anniversary",
                    "precision": "full",
                    "year": 2020,
                    "month": 1,
                    "day": 1,
                },
            ],
        }

        person_data = _transform_contact_to_google_person(contact)

        assert "birthdays" not in person_data
        assert "events" not in person_data
