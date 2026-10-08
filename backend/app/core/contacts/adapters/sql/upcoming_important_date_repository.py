"""SQL adapter for the upcoming-dates candidate read.

**One statement, and it filters on pairs rather than on dates.** A stored
important date is a month and a day, sometimes with a year, so there is no
column to compare against "the next seven days". What the caller supplies
instead is the set of ``(month, day)`` pairs that window could possibly contain
— at most 91 of them, and eight for the week the dashboard asks about — and the
statement matches rows against that set. Deciding *which year* a pair lands in,
and what it makes, stays in ``resolve_occurrence`` where it is unit-testable.

**The pairs arrive as two parallel integer arrays**, joined through a
multi-argument ``unnest``. Not a literal ``IN (VALUES …)`` list, which would
build a different statement for every window length and defeat the driver's
statement cache; and not two independent ``= ANY`` filters on month and day,
which would match 3 August for a window covering 14 September — the pair has to
be matched as a pair. Passing arrays as parameters is the shape this codebase
already uses for batch reads.

**No precision filter.** ``ck_important_dates_year_precision`` guarantees a
``year``-precision row has a NULL month and day, so the pair join cannot match
one; and precision is ``resolve_occurrence``'s authority, checked once there. A
second rule here that had to agree with that one is the defect shape ITER18-004
Phase 9 rejected for date types, and it would be no better applied to precision.

**Not scoped by user**, because ``contacts`` has no owner column in this schema
and every other contacts repository is likewise unscoped — the divergence
ITER18-004 Phase 10 recorded for the importance read, carried forward rather
than solved for one query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy import text

from app.core.contacts.models.repositories import UpcomingImportantDateRepository
from app.core.contacts.models.upcoming_dates import (
    ContactImportantDate,
    UpcomingDateContact,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncConnection

_CANDIDATES_QUERY = text("""
    SELECT
        d.id,
        d.contact_id,
        d.date_type,
        d.precision,
        d.year,
        d.month,
        d.day,
        d.custom_date_type_id,
        cdt.name AS custom_date_type_name,
        d.created_at,
        d.updated_at,
        c.user_id,
        c.first_name,
        c.middle_name,
        c.last_name,
        c.nick_name,
        c.photo_url
    FROM contact_important_dates d
    JOIN unnest(CAST(:months AS integer[]), CAST(:days AS integer[]))
        AS window_day(month, day)
        ON window_day.month = d.month AND window_day.day = d.day
    JOIN contacts c ON c.id = d.contact_id AND c.user_id = :user_id
    LEFT JOIN custom_date_types cdt ON cdt.id = d.custom_date_type_id
    ORDER BY d.contact_id, d.id
""")


class SqlUpcomingImportantDateRepository(UpcomingImportantDateRepository):
    """Reads the important dates a window could contain, from PostgreSQL."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Bind the read to a connection.

        Args:
            connection: The request's connection. The read opens no transaction
                of its own.
        """
        self.conn = connection

    async def candidates_for(
        self, month_days: Sequence[tuple[int, int]], *, user_id: str
    ) -> list[ContactImportantDate]:
        """Every important date of ``user_id``'s contacts carrying one of ``month_days``.

        Args:
            month_days: The ``(month, day)`` pairs to match. An empty sequence
                short circuits without a round trip — the case for a user with
                no dates at all is a window that finds nothing, not a query that
                finds nothing.

        Returns:
            The rows in a stable order, each with its contact attached.
        """
        if not month_days:
            return []

        result = await self.conn.execute(
            _CANDIDATES_QUERY,
            {
                "months": [month for month, _ in month_days],
                "days": [day for _, day in month_days],
                "user_id": user_id,
            },
        )
        return [
            ContactImportantDate(
                important_date=ImportantDate(
                    id=row.id,
                    contact_id=row.contact_id,
                    date_type=ImportantDateType(row.date_type),
                    precision=DatePrecision(row.precision),
                    year=row.year,
                    month=row.month,
                    day=row.day,
                    custom_date_type_id=row.custom_date_type_id,
                    custom_date_type_name=row.custom_date_type_name,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                ),
                contact=UpcomingDateContact(
                    id=row.contact_id,
                    display_name=_display_name(
                        row.user_id,
                        row.first_name,
                        row.middle_name,
                        row.last_name,
                        row.nick_name,
                    ),
                    photo_url=row.photo_url,
                ),
            )
            for row in result
        ]


def _display_name(
    user_id: str,
    first_name: str,
    middle_name: str | None,
    last_name: str | None,
    nick_name: str | None,
) -> str:
    """The name a row shows, by the contacts domain's own rule.

    Built through ``Contact.get_display_name`` rather than assembled in SQL, so
    the dashboard shows the nickname the rest of the app shows. The agenda's
    participant list does concatenate names in SQL and therefore ignores
    nicknames; that is a divergence in the *journal* domain's query, not a
    precedent to copy into the contacts domain's own read.
    """
    return Contact(
        first_name=first_name,
        user_id=user_id,
        middle_name=middle_name,
        last_name=last_name,
        nick_name=nick_name,
    ).get_display_name()
