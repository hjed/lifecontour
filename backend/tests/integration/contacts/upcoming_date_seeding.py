"""Seeding for the upcoming-dates read's tables, shared by its two suites.

Written for `test_upcoming_important_dates_integration.py` and extracted when
the daily summary's date input became a second caller — moved into shared
seeding rather than copied, as the tasks suites' helpers were before them.
Three near-identical ``INSERT`` helpers in two files is the shape the
duplication gate exists to catch, and a second copy would be free to drift from
the schema the first was written against.

Every helper takes ``now`` rather than reading a module constant: the two suites
anchor on different days, and a row's ``created_at`` is an importance signal, so
a shared default would be a fixture deciding something a test should.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy import text

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncConnection


async def seed_contact(
    connection: AsyncConnection,
    contact_id: int,
    *,
    now: datetime,
    first_name: str = "Ada",
    last_name: str | None = "Lovelace",
    middle_name: str | None = None,
    nick_name: str | None = None,
    photo_url: str | None = None,
    is_favourite: bool = False,
) -> None:
    """A bare contact with the display fields a dashboard row shows.

    ``is_favourite`` is here rather than left to a follow-up ``UPDATE`` because
    it is the first of the three importance signals, and a caller ordering two
    contacts on one day needs it at seeding time.
    """
    await connection.execute(
        text("""
            INSERT INTO contacts (
                id, first_name, middle_name, last_name, nick_name, photo_url,
                is_favourite, created_at, updated_at
            )
            VALUES (:id, :first_name, :middle_name, :last_name, :nick_name,
                    :photo_url, :is_favourite, :now, :now)
        """),
        {
            "id": contact_id,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "nick_name": nick_name,
            "photo_url": photo_url,
            "is_favourite": is_favourite,
            "now": now,
        },
    )


async def seed_important_date(
    connection: AsyncConnection,
    date_id: int,
    contact_id: int,
    *,
    now: datetime,
    month: int | None,
    day: int | None,
    year: int | None = None,
    precision: DatePrecision = DatePrecision.DAY_MONTH,
    date_type: ImportantDateType = ImportantDateType.BIRTHDAY,
    custom_date_type_id: int | None = None,
) -> None:
    """One stored important date, at whatever precision the test needs.

    The precision is explicit rather than inferred from the components, because
    a suite addressed to this read has to be able to store a ``YEAR``-precision
    row — the one combination that yields no occurrence at all.
    """
    await connection.execute(
        text("""
            INSERT INTO contact_important_dates (
                id, contact_id, date_type, precision, year, month, day,
                custom_date_type_id, created_at, updated_at
            )
            VALUES (:id, :contact_id, :date_type, :precision, :year, :month,
                    :day, :custom_date_type_id, :now, :now)
        """),
        {
            "id": date_id,
            "contact_id": contact_id,
            "date_type": date_type.value,
            "precision": precision.value,
            "year": year,
            "month": month,
            "day": day,
            "custom_date_type_id": custom_date_type_id,
            "now": now,
        },
    )


async def seed_custom_date_type(
    connection: AsyncConnection,
    type_id: int,
    *,
    now: datetime,
    name: str = "Sobriety",
) -> None:
    """A user-named date type, so its name can travel with the row."""
    await connection.execute(
        text("""
            INSERT INTO custom_date_types (id, name, created_at, updated_at)
            VALUES (:id, :name, :now, :now)
        """),
        {"id": type_id, "name": name, "now": now},
    )
