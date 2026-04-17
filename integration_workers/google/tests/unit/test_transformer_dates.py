"""
Unit tests for Google Contacts transformer date mapping.

Tests the inbound conversion of Google People API birthdays and events
fields to internal ImportantDate entities.
"""

import sys

import pytest

sys.path.insert(0, "/core_shared")

from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

from api_models import (
    GoogleBirthday,
    GoogleDate,
    GoogleName,
    GooglePerson,
    GooglePersonEvent,
)
from transformer import GoogleContactTransformer


@pytest.fixture
def transformer() -> GoogleContactTransformer:
    """Create GoogleContactTransformer instance."""
    return GoogleContactTransformer()


class TestBirthdayTransformation:
    """Test inbound transformation of Google birthdays to ImportantDate."""

    def test_birthday_full_date(self, transformer: GoogleContactTransformer) -> None:
        """Birthday with year, month, and day maps to BIRTHDAY/FULL."""
        person = GooglePerson(
            resourceName="people/c1",
            names=[GoogleName(givenName="Test")],
            birthdays=[GoogleBirthday(date=GoogleDate(year=1990, month=5, day=20))],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 1
        date = contact.important_dates[0]
        assert date.date_type == ImportantDateType.BIRTHDAY
        assert date.precision == DatePrecision.FULL
        assert date.year == 1990
        assert date.month == 5
        assert date.day == 20

    def test_birthday_year_zero_maps_to_day_month(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Birthday with year=0 maps to BIRTHDAY/DAY_MONTH precision."""
        person = GooglePerson(
            resourceName="people/c2",
            names=[GoogleName(givenName="Test")],
            birthdays=[GoogleBirthday(date=GoogleDate(year=0, month=3, day=15))],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 1
        date = contact.important_dates[0]
        assert date.date_type == ImportantDateType.BIRTHDAY
        assert date.precision == DatePrecision.DAY_MONTH
        assert date.year is None
        assert date.month == 3
        assert date.day == 15

    def test_birthday_month_day_zero_maps_to_year(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Birthday with month=0 and day=0 maps to BIRTHDAY/YEAR precision."""
        person = GooglePerson(
            resourceName="people/c3",
            names=[GoogleName(givenName="Test")],
            birthdays=[GoogleBirthday(date=GoogleDate(year=1985, month=0, day=0))],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 1
        date = contact.important_dates[0]
        assert date.date_type == ImportantDateType.BIRTHDAY
        assert date.precision == DatePrecision.YEAR
        assert date.year == 1985
        assert date.month is None
        assert date.day is None

    def test_birthday_no_date_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Birthday with no date object is skipped."""
        person = GooglePerson(
            resourceName="people/c4",
            names=[GoogleName(givenName="Test")],
            birthdays=[GoogleBirthday(date=None)],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is None

    def test_birthday_all_zeros_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Birthday where all date components are zero is skipped (returns None if no valid dates)."""
        person = GooglePerson(
            resourceName="people/c5",
            names=[GoogleName(givenName="Test")],
            birthdays=[GoogleBirthday(date=GoogleDate(year=0, month=0, day=0))],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is None

    def test_birthday_none_components_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Birthday where all date components are None is skipped (returns None if no valid dates)."""
        person = GooglePerson(
            resourceName="people/c6",
            names=[GoogleName(givenName="Test")],
            birthdays=[
                GoogleBirthday(date=GoogleDate(year=None, month=None, day=None))
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is None


class TestEventTransformation:
    """Test inbound transformation of Google events to ImportantDate."""

    def test_anniversary_event_maps_to_marriage_anniversary(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Event with type='anniversary' maps to MARRIAGE_ANNIVERSARY."""
        person = GooglePerson(
            resourceName="people/c10",
            names=[GoogleName(givenName="Test")],
            events=[
                GooglePersonEvent(
                    date=GoogleDate(year=2015, month=6, day=20),
                    type="anniversary",
                )
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 1
        date = contact.important_dates[0]
        assert date.date_type == ImportantDateType.MARRIAGE_ANNIVERSARY
        assert date.precision == DatePrecision.FULL
        assert date.year == 2015
        assert date.month == 6
        assert date.day == 20

    def test_anniversary_event_day_month_precision(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Anniversary event with year=0 maps to DAY_MONTH precision."""
        person = GooglePerson(
            resourceName="people/c11",
            names=[GoogleName(givenName="Test")],
            events=[
                GooglePersonEvent(
                    date=GoogleDate(year=0, month=12, day=25),
                    type="anniversary",
                )
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 1
        date = contact.important_dates[0]
        assert date.date_type == ImportantDateType.MARRIAGE_ANNIVERSARY
        assert date.precision == DatePrecision.DAY_MONTH
        assert date.year is None

    def test_unknown_event_type_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Events with unsupported types are silently skipped (returns None if no valid dates)."""
        person = GooglePerson(
            resourceName="people/c12",
            names=[GoogleName(givenName="Test")],
            events=[
                GooglePersonEvent(
                    date=GoogleDate(year=2020, month=1, day=1),
                    type="other",
                ),
                GooglePersonEvent(
                    date=GoogleDate(year=2020, month=1, day=1),
                    type="custom_event",
                ),
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is None

    def test_event_no_date_skipped(self, transformer: GoogleContactTransformer) -> None:
        """Event with no date is skipped (returns None if no valid dates)."""
        person = GooglePerson(
            resourceName="people/c13",
            names=[GoogleName(givenName="Test")],
            events=[
                GooglePersonEvent(date=None, type="anniversary"),
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is None

    def test_event_no_type_skipped(self, transformer: GoogleContactTransformer) -> None:
        """Event with no type is skipped (returns None if no valid dates)."""
        person = GooglePerson(
            resourceName="people/c14",
            names=[GoogleName(givenName="Test")],
            events=[
                GooglePersonEvent(
                    date=GoogleDate(year=2020, month=1, day=1),
                    type=None,
                ),
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is None


class TestCombinedDateTransformation:
    """Test combined birthday + event transformation."""

    def test_birthday_and_anniversary_combined(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Both birthday and anniversary event produce two ImportantDate entries."""
        person = GooglePerson(
            resourceName="people/c20",
            names=[GoogleName(givenName="Test")],
            birthdays=[GoogleBirthday(date=GoogleDate(year=1990, month=5, day=20))],
            events=[
                GooglePersonEvent(
                    date=GoogleDate(year=2015, month=6, day=20),
                    type="anniversary",
                )
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 2
        types = {d.date_type for d in contact.important_dates}
        assert ImportantDateType.BIRTHDAY in types
        assert ImportantDateType.MARRIAGE_ANNIVERSARY in types

    def test_empty_birthdays_and_events_yields_none(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """When Google provides no birthdays and no events, important_dates is None.

        This preserves local-only dates during sync updates.
        """
        person = GooglePerson(
            resourceName="people/c21",
            names=[GoogleName(givenName="Test")],
            birthdays=[],
            events=[],
        )

        contact = transformer.transform_person(person)

        # Empty lists from Google = no date data provided = preserve local
        assert contact.important_dates is None

    def test_birthday_present_but_no_events_sets_list(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """When birthdays has data but events is empty, important_dates is set."""
        person = GooglePerson(
            resourceName="people/c22",
            names=[GoogleName(givenName="Test")],
            birthdays=[GoogleBirthday(date=GoogleDate(year=1990, month=5, day=20))],
            events=[],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is not None
        assert len(contact.important_dates) == 1

    def test_no_date_fields_default_yields_none(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """When person has default empty lists for dates, important_dates is None."""
        person = GooglePerson(
            resourceName="people/c23",
            names=[GoogleName(givenName="Test")],
        )

        contact = transformer.transform_person(person)

        assert contact.important_dates is None
