"""Resolving a journal's date, and the future-dated rule, in the user's timezone.

A journal's **date** is the local date of its ``event_date_range.start`` in the
acting user's *configured* timezone, and it is the date the tasks model judges
its future-dated invariant against. A multi-day journal is therefore dated by
the day it *starts*: a trip that began yesterday and runs until tomorrow is
past, however much of it is still ahead.

This is intended to be the date the journal list groups a journal under, but
that equality does **not** hold unconditionally today: ``groupJournalsByDay``
groups in the *browser's* timezone, which differs when a user travels or has
configured another zone. See *Journal date resolution (user-local)* in
``docs/architecture/domain-architecture.md``.

The module is split deliberately:

- the **pure functions** take a ``ZoneInfo`` and hold all the calendar logic, so
  a caller resolving many journals fetches the user's timezone once rather than
  once per journal;
- :class:`JournalDateResolver` is the thin async wrapper that supplies that
  timezone from ``UserSettingsRepository`` (UTC when unset or unrecognised).

It lives in the journal domain because a journal's date is journal knowledge:
``app/core/settings`` must stay a leaf that any domain can import, and the
dashboard's agenda (which reads journals, not tasks) would not sensibly reach
into the tasks domain for it.

``now`` is injectable throughout so the day boundary can be tested either side
of local midnight. Callers with a service-level ``anchor: date`` convention —
the outdoor dashboard, and the home dashboard to come — obtain that anchor from
:meth:`JournalDateResolver.today` and keep their own signature.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from core_shared.models.journals import EventDateRange

from app.core.settings.timezone_utils import resolve_timezone, to_user_tz

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from core_shared.models.journals import Journal

    from app.core.settings.models import UserSettingsRepository


def local_date(moment: datetime.datetime, tz: ZoneInfo) -> datetime.date:
    """The calendar date ``moment`` falls on in ``tz``.

    Naive datetimes are read as UTC, matching the storage convention
    ``to_user_tz`` documents.
    """
    return to_user_tz(moment, tz).date()


def journal_date(journal: Journal, tz: ZoneInfo) -> datetime.date:
    """The journal's date: the local date its event date range **starts** on."""
    return local_date(journal.event_date_range.start, tz)


def today_in(tz: ZoneInfo, now: datetime.datetime | None = None) -> datetime.date:
    """Today's date in ``tz`` — never UTC's date."""
    return local_date(now, tz) if now else datetime.datetime.now(tz).date()


def is_future_dated(
    journal: Journal, tz: ZoneInfo, now: datetime.datetime | None = None
) -> bool:
    """Whether the journal's date is strictly after today in ``tz``.

    Today is not the future: a journal starting later the same local day is not
    future-dated, per the specification's fourth task invariant.
    """
    return journal_date(journal, tz) > today_in(tz, now)


def local_day_window(day: datetime.date, tz: ZoneInfo) -> EventDateRange:
    """``day`` as an instant range: local midnight to its final microsecond.

    ``ZoneInfo`` resolves each end's offset from its own local wall time, so a
    day whose clocks change is the 23 or 25 hours it really is. Building both
    ends from the date — the idiom ``OutdoorDashboardService._window`` uses —
    rather than by zeroing the components of some instant inside the day also
    keeps the result independent of which instant that was, ``fold`` included.
    """
    return EventDateRange(
        start=datetime.datetime.combine(day, datetime.time.min, tz),
        end=datetime.datetime.combine(day, datetime.time.max, tz),
    )


class JournalDateResolver:
    """Resolves journal dates against the acting user's configured timezone.

    Read-only and stateless beyond its repository, so it opens no unit of work.
    Batch callers should take :meth:`timezone_for` once and use the module's pure
    functions, rather than calling :meth:`is_future_dated` per journal.
    """

    def __init__(self, user_settings_repo: UserSettingsRepository) -> None:
        self.user_settings_repo = user_settings_repo

    async def timezone_for(self, user_id: str) -> ZoneInfo:
        """The user's configured timezone (UTC when unset or unrecognised)."""
        return resolve_timezone(await self.user_settings_repo.get_timezone(user_id))

    async def today(
        self, user_id: str, now: datetime.datetime | None = None
    ) -> datetime.date:
        """Today's date for the user, in their timezone."""
        return today_in(await self.timezone_for(user_id), now)

    async def is_future_dated(
        self, user_id: str, journal: Journal, now: datetime.datetime | None = None
    ) -> bool:
        """Whether the journal is future-dated for the user, in their timezone."""
        return is_future_dated(journal, await self.timezone_for(user_id), now)
