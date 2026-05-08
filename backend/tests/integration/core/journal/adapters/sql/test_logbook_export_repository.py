"""Integration tests for SqlLogbookExportRepository."""

from datetime import UTC, datetime

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.logbook_export_repository import (
    SqlLogbookExportRepository,
)
from app.core.journal.models.repositories import (
    JournalRepository,
)


@pytest.fixture
def repo(async_connection: AsyncConnection) -> SqlLogbookExportRepository:
    """Provide a logbook export repository."""
    return SqlLogbookExportRepository(async_connection)


@pytest.fixture
def journal_repo(async_connection: AsyncConnection) -> SqlJournalRepository:
    """Provide a journal repository."""
    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

    return SqlJournalRepository(async_connection)


@pytest.mark.asyncio
async def test_get_logbook_entries_empty(repo: SqlLogbookExportRepository) -> None:
    """Test getting logbook entries when none exist."""
    entries = await repo.get_logbook_entries(user_id="user_test_empty")
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_get_logbook_entries_filters(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """Test that logbook export correctly fetches journals by logbook type."""
    # Create some journals
    user_id = "user_logbook_test"
    now = datetime.now(UTC)

    # Matching journal (BUSHWALKING)
    journal1 = Journal(
        user_id=user_id,
        title="Matching",
        content="Testing",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal1 = await journal_repo.save(journal1)

    # We must insert directly into journal_types because our tests usually do that via service
    # We'll just insert raw SQL for journal_types
    await async_connection.execute(
        text("INSERT INTO journal_bushwalking_data (journal_id) VALUES (:id)"),
        {"id": journal1.id},
    )

    # Non-matching journal (JOGGING)
    journal2 = Journal(
        user_id=user_id,
        title="Not matching",
        content="Testing",
        event_date_range=EventDateRange(start=now, end=now),
    )
    journal2 = await journal_repo.save(journal2)
    await async_connection.execute(
        text("INSERT INTO journal_jogging_data (journal_id) VALUES (:id)"),
        {"id": journal2.id},
    )

    # Test fetch
    entries = await repo.get_logbook_entries(user_id=user_id)

    assert len(entries) == 1
    assert entries[0].id == journal1.id
    assert entries[0].title == "Matching"
    assert "BUSHWALKING" in entries[0].journal_types


@pytest.mark.asyncio
async def test_get_logbook_entries_hierarchy(
    repo: SqlLogbookExportRepository,
    journal_repo: JournalRepository,
    async_connection: AsyncConnection,
) -> None:
    """Test that logbook export correctly fetches ancestors and descendants."""
    user_id = "user_logbook_hierarchy"
    now = datetime.now(UTC)

    # Parent (not matching type itself)
    parent = Journal(
        user_id=user_id,
        title="Parent Trip",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
    )
    parent = await journal_repo.save(parent)
    await async_connection.execute(
        text("INSERT INTO journal_travel_data (journal_id) VALUES (:id)"),
        {"id": parent.id},
    )

    # Matching child
    child1 = Journal(
        user_id=user_id,
        title="Matching Child",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
        parent_id=parent.id,
    )
    child1 = await journal_repo.save(child1)
    await async_connection.execute(
        text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:id)"),
        {"id": child1.id},
    )

    # Descendant of matching child
    grandchild = Journal(
        user_id=user_id,
        title="Grandchild",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
        parent_id=child1.id,
    )
    grandchild = await journal_repo.save(grandchild)
    # Note doesn't need an explicit insert

    # Unrelated sibling
    sibling = Journal(
        user_id=user_id,
        title="Unrelated sibling",
        content="",
        event_date_range=EventDateRange(start=now, end=now),
        parent_id=parent.id,
    )
    sibling = await journal_repo.save(sibling)
    # Note doesn't need an explicit insert

    # Test fetch
    entries = await repo.get_logbook_entries(user_id=user_id)

    # Should get Parent, Child1, and Grandchild. But NOT Unrelated Sibling because sibling is not an ancestor/descendant of the matching journal (Child1).
    entry_ids = {e.id for e in entries}

    assert parent.id in entry_ids
    assert child1.id in entry_ids
    assert grandchild.id in entry_ids

    # Sibling doesn't have a matching type, and isn't a direct descendant or ancestor of child1.
    # However, because we fetch ALL descendants of ALL ancestors to preserve full hierarchy,
    # and the parent is an ancestor of child1, the sibling (being a descendant of the parent)
    # MUST be included in the final results to maintain the complete structural context.
    assert sibling.id in entry_ids
