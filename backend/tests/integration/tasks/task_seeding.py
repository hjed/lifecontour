"""Shared seeding helpers for the task integration tests.

Both the constraint tests and the repository tests need the same three things —
a journal to anchor to, a contact to link, and a row count to assert against —
so they live here rather than being copied per file.

Journals are created through ``SqlJournalRepository`` so the anchors are real
journal rows; contacts are inserted directly because the contact domain's own
creation path is irrelevant to what these tests assert.
"""

from datetime import UTC, datetime, timedelta

from core_shared.models.journals import EventDateRange, Journal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

USER_ID = "test-user-123"
# A second, unrelated owner. Owner scoping is only worth asserting against real
# rows belonging to someone else, never against a merely absent id.
OTHER_USER_ID = "other-user-456"


async def create_journal(
    journal_repository: SqlJournalRepository,
    *,
    title: str = "Anchor Journal",
    days_offset: int = 0,
    user_id: str = USER_ID,
) -> int:
    """Create a journal and return its id."""
    start = datetime.now(UTC) + timedelta(days=days_offset)
    journal = await journal_repository.save(
        Journal(
            user_id=user_id,
            title=title,
            content="content",
            event_date_range=EventDateRange(
                start=start, end=start + timedelta(hours=1)
            ),
        )
    )
    assert journal.id is not None
    return journal.id


async def create_contact(conn: AsyncConnection, *, first_name: str = "Sarah") -> int:
    """Create a contact and return its id."""
    contact_id = (
        await conn.execute(
            text("INSERT INTO contacts (first_name) VALUES (:first_name) RETURNING id"),
            {"first_name": first_name},
        )
    ).scalar_one()
    return int(contact_id)


async def count(conn: AsyncConnection, sql: str, params: dict[str, int]) -> int:
    """Run a counting query and return the count."""
    return int((await conn.execute(text(sql), params)).scalar_one())
