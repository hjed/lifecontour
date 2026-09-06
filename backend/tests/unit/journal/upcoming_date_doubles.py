"""Doubles for the contacts read the summary's upcoming-dates input comes from.

Shared by the prompt builder's suite and the assembler's because both need the
same three-step fixture — a stored row, the occurrence the rule resolves for it,
and the answer ``UpcomingImportantDatesService`` returns — and two copies of an
``ImportantDate`` builder is the shape the duplication gate exists to catch.

**The occurrence is derived, never hand-built.** ``resolve_occurrence`` decides
``years``, ``days_away`` and ``observed_for_leap_day``, the reasoning the task
suites give for going through ``build_task_read_model``: a fixture that set
those itself could assert a rendering the real rule never produces, and the
leap-day substitution is exactly the one a hand-built fixture would get wrong.
"""

from __future__ import annotations

from datetime import date

from core_shared.models.contacts.entities import ImportantDate
from core_shared.models.contacts.important_date_occurrence import resolve_occurrence
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.date_window import UpcomingWindow

from app.core.contacts.models.importance import ContactImportance
from app.core.contacts.models.upcoming_dates import (
    UpcomingContactDate,
    UpcomingContactDates,
    UpcomingDateContact,
    upcoming_dates_window,
)

#: The day both suites anchor on, and the window it makes. Named here so the two
#: cannot drift onto different weeks while sharing these builders.
DOUBLE_TODAY = date(2026, 4, 27)
DEFAULT_DATE_WINDOW = upcoming_dates_window(DOUBLE_TODAY)


def stored_date(
    date_id: int,
    *,
    month: int,
    day: int,
    year: int | None = None,
    date_type: ImportantDateType = ImportantDateType.BIRTHDAY,
    custom_date_type_id: int | None = None,
    custom_date_type_name: str | None = None,
) -> ImportantDate:
    """One stored important date, at the precision its components imply.

    A year makes it ``FULL`` and its absence ``DAY_MONTH``, which is the rule
    ``ck_important_dates_year_precision`` already enforces — spelling the
    precision out per fixture would let a test assert a combination the database
    cannot hold.
    """
    return ImportantDate(
        id=date_id,
        contact_id=100 + date_id,
        date_type=date_type,
        precision=DatePrecision.FULL if year is not None else DatePrecision.DAY_MONTH,
        year=year,
        month=month,
        day=day,
        custom_date_type_id=custom_date_type_id,
        custom_date_type_name=custom_date_type_name,
    )


def occurring(
    stored: ImportantDate,
    *,
    window: UpcomingWindow | None = None,
    name: str = "Ada Lovelace",
    is_favourite: bool = False,
) -> UpcomingContactDate:
    """The date as the contacts read hands it over, occurrence and all."""
    resolved = resolve_occurrence(
        stored,
        first_day=(window or DEFAULT_DATE_WINDOW).first_day,
        last_day=(window or DEFAULT_DATE_WINDOW).last_day,
    )
    if resolved is None:  # pragma: no cover - a fixture outside its own window
        raise AssertionError("fixture does not occur in the window it was given")
    return UpcomingContactDate(
        occurrence=resolved,
        contact=UpcomingDateContact(
            id=stored.contact_id, display_name=name, photo_url=None
        ),
        importance=ContactImportance(
            contact_id=stored.contact_id,
            is_favourite=is_favourite,
            journal_count_30d=0,
            activity_count_30d=0,
            last_activity_at=None,
        ),
    )


def coming_up(
    *dates: UpcomingContactDate, window: UpcomingWindow | None = None
) -> UpcomingContactDates:
    """The contacts read's answer for the current day, window and all."""
    return UpcomingContactDates(window=window or DEFAULT_DATE_WINDOW, dates=dates)
