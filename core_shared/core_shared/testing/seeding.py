"""Shared database seeding for integration tests.

Every backend and worker integration test that needs a contact row seeds it
through :func:`seed_contact` (or :func:`seed_contacts`, in bulk), so what a
contact row requires is written down in this one module. A raw
``INSERT INTO contacts`` anywhere else in a test is rejected by
``backend/tests/unit/test_contact_seeding_guard.py``.

Backend tests import it from ``tests.integration.contact_seeding``, which pairs
it with the backend's test identity; worker tests import it from here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

# One static statement serves every call shape: an unnamed id draws from the
# table's sequence and unnamed timestamps are "now", exactly as the column
# defaults would.
_INSERT_CONTACT = text("""
    INSERT INTO contacts (
        id, first_name, middle_name, last_name, nick_name, company, job_title,
        photo_url, is_favourite, created_at, updated_at
    )
    VALUES (
        COALESCE(
            CAST(:id AS INTEGER),
            nextval(pg_get_serial_sequence('contacts', 'id'))
        ),
        :first_name, :middle_name, :last_name, :nick_name, :company, :job_title,
        :photo_url, :is_favourite,
        COALESCE(CAST(:created_at AS TIMESTAMPTZ), now()),
        COALESCE(CAST(:updated_at AS TIMESTAMPTZ), now())
    )
    RETURNING id
""")


async def seed_contact(
    conn: AsyncConnection | AsyncSession,
    *,
    first_name: str = "Sarah",
    last_name: str | None = None,
    middle_name: str | None = None,
    nick_name: str | None = None,
    company: str | None = None,
    job_title: str | None = None,
    photo_url: str | None = None,
    is_favourite: bool = False,
    contact_id: int | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> int:
    """Insert a contact row and return its id.

    ``contact_id`` pins the id, for tests that address fixed ids; it does not
    advance the table's sequence, so a test mixing pinned and drawn ids must
    pick pinned ids well clear of the drawn ones. ``created_at`` and
    ``updated_at`` default to the transaction's ``now()``.
    """
    result = await conn.execute(
        _INSERT_CONTACT,
        {
            "id": contact_id,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "nick_name": nick_name,
            "company": company,
            "job_title": job_title,
            "photo_url": photo_url,
            "is_favourite": is_favourite,
            "created_at": created_at,
            "updated_at": updated_at,
        },
    )
    return int(result.scalar_one())


_INSERT_NUMBERED_CONTACTS = text("""
    INSERT INTO contacts (first_name)
    SELECT CAST(:prefix AS TEXT) || ' ' || n
    FROM generate_series(1, :count) AS n
    ORDER BY n
    RETURNING id
""")


async def seed_contacts(
    conn: AsyncConnection | AsyncSession,
    count: int,
    *,
    first_name_prefix: str = "Contact",
) -> list[int]:
    """Insert ``count`` bare contacts named ``"<prefix> 1"`` … in one statement.

    For tests that need more contacts than one-at-a-time seeding can afford —
    tens of thousands of round trips would dominate the suite. Returns the ids
    in numbering order.
    """
    result = await conn.execute(
        _INSERT_NUMBERED_CONTACTS, {"prefix": first_name_prefix, "count": count}
    )
    return [int(contact_id) for contact_id in result.scalars()]
