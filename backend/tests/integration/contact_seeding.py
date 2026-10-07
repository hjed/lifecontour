"""How a backend integration test creates a contact, and whose it is.

``seed_contact`` (and ``seed_contacts``, for bulk) is the one way to put a
contact row in the database from a test: ``tests/unit/test_contact_seeding_guard.py``
rejects raw inserts. The SQL lives in ``core_shared.testing.seeding`` so the
workers' tests share it.

``TEST_USER_ID`` is the acting user of every authenticated test client: the
``test_user`` fixture reads it, so a test that seeds rows for "the test user"
and the client that reads them cannot disagree. It is the owner a contact is
seeded for unless the test names another (``OTHER_USER_ID`` for a foreign one).
"""

from datetime import datetime
from typing import Final

from core_shared.testing import seeding
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

TEST_USER_ID: Final = "test-user-123"
# A second, unrelated owner: ownership is only worth asserting against real rows
# belonging to someone else, never against a merely absent id.
OTHER_USER_ID: Final = "other-user-456"


async def seed_contact(
    conn: AsyncConnection | AsyncSession,
    *,
    user_id: str = TEST_USER_ID,
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
    """Insert a contact row, owned by the test user by default; return its id."""
    return await seeding.seed_contact(
        conn,
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        nick_name=nick_name,
        company=company,
        job_title=job_title,
        photo_url=photo_url,
        is_favourite=is_favourite,
        contact_id=contact_id,
        created_at=created_at,
        updated_at=updated_at,
    )


async def seed_contacts(
    conn: AsyncConnection | AsyncSession,
    count: int,
    *,
    user_id: str = TEST_USER_ID,
    first_name_prefix: str = "Contact",
) -> list[int]:
    """Insert ``count`` numbered contacts in one statement; see ``seeding``."""
    return await seeding.seed_contacts(
        conn, count, user_id=user_id, first_name_prefix=first_name_prefix
    )


__all__ = ["OTHER_USER_ID", "TEST_USER_ID", "seed_contact", "seed_contacts"]
